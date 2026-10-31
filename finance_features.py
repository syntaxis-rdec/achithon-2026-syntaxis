import json
from datetime import date
from decimal import Decimal, InvalidOperation

import pandas as pd

import database as db


CENT = Decimal("0.01")


def parse_money(value):
    try:
        amount = Decimal(str(value))

        if not amount.is_finite():
            raise ValueError("Amount must be finite.")

        rounded = amount.quantize(CENT)

        if amount != rounded:
            raise ValueError("Use at most two decimal places.")

        if rounded <= 0:
            raise ValueError("Amount must be positive.")

        return rounded

    except (InvalidOperation, TypeError):
        raise ValueError("Enter a valid positive amount.")


def initialize_features():
    db.create_tables()

    with db.get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event TEXT NOT NULL,
                entity TEXT NOT NULL,
                entity_id INTEGER,
                details TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_alloc_invoice
            ON allocations(invoice_id);

            CREATE INDEX IF NOT EXISTS idx_alloc_payment
            ON allocations(payment_id);

            CREATE INDEX IF NOT EXISTS idx_match_status
            ON match_suggestions(status);

            CREATE TRIGGER IF NOT EXISTS activity_allocation_insert
            AFTER INSERT ON allocations
            BEGIN
                INSERT INTO activity_log (
                    event, entity, entity_id, details
                )
                VALUES (
                    'allocation_created',
                    'allocation',
                    NEW.id,
                    'Invoice DB ID: ' || NEW.invoice_id ||
                    '; Payment DB ID: ' || NEW.payment_id ||
                    '; Amount: ' || NEW.allocated_amount
                );
            END;

            CREATE TRIGGER IF NOT EXISTS activity_allocation_update
            AFTER UPDATE OF allocated_amount ON allocations
            WHEN OLD.allocated_amount <> NEW.allocated_amount
            BEGIN
                INSERT INTO activity_log (
                    event, entity, entity_id, details
                )
                VALUES (
                    'allocation_updated',
                    'allocation',
                    NEW.id,
                    'Previous: ' || OLD.allocated_amount ||
                    '; New total: ' || NEW.allocated_amount
                );
            END;

            CREATE TRIGGER IF NOT EXISTS activity_review_update
            AFTER UPDATE OF status ON match_suggestions
            WHEN OLD.status <> NEW.status
            BEGIN
                INSERT INTO activity_log (
                    event, entity, entity_id, details
                )
                VALUES (
                    'review_decision',
                    'suggestion',
                    NEW.id,
                    OLD.status || ' -> ' || NEW.status
                );
            END;
        """)


def get_activity(limit=250):
    with db.get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT id AS ID,
                   event AS Event,
                   entity AS Entity,
                   entity_id AS "Record ID",
                   details AS Details,
                   created_at AS "Time (UTC)"
            FROM activity_log
            ORDER BY id DESC
            LIMIT ?
            """,
            conn,
            params=(int(limit),),
        )


def load_matching_data():
    with db.get_connection() as conn:
        invoices = pd.read_sql_query(
            """
            SELECT invoice_id, customer_name, amount,
                   invoice_date, reference
            FROM invoices
            """,
            conn,
        )

        payments = pd.read_sql_query(
            """
            SELECT payment_id, customer_name, amount,
                   payment_date, reference, description
            FROM payments
            """,
            conn,
        )

    return invoices, payments


def get_invoice_age_report():
    balances = pd.DataFrame(db.get_invoice_balances())

    if balances.empty:
        return balances

    with db.get_connection() as conn:
        dates = pd.read_sql_query(
            """
            SELECT invoice_id AS "Invoice ID",
                   invoice_date AS "Invoice Date"
            FROM invoices
            """,
            conn,
        )

    report = balances.merge(dates, on="Invoice ID", how="left")

    parsed = pd.to_datetime(
        report["Invoice Date"],
        errors="coerce",
        utc=True,
    )

    today = pd.Timestamp(date.today(), tz="UTC")

    report["Age (days)"] = (
        today - parsed.dt.normalize()
    ).dt.days.astype("Int64")

    def age_band(value):
        if pd.isna(value):
            return "Unknown date"
        if value < 0:
            return "Future dated"
        if value <= 30:
            return "0–30 days"
        if value <= 60:
            return "31–60 days"
        if value <= 90:
            return "61–90 days"
        return "91+ days"

    report["Age band"] = report["Age (days)"].map(age_band)
    return report


def review_match(suggestion_id, action, amount=None):
    """Review and allocate in one database transaction."""
    conn = db.get_connection()

    try:
        conn.execute("BEGIN IMMEDIATE")

        suggestion = conn.execute(
            """
            SELECT invoice_id, payment_id, status
            FROM match_suggestions
            WHERE id = ?
            """,
            (int(suggestion_id),),
        ).fetchone()

        if suggestion is None:
            raise ValueError("Suggestion not found.")

        invoice_id, payment_id, status = suggestion

        if status != "pending":
            raise ValueError("This suggestion has already been reviewed.")

        if action == "reject":
            conn.execute(
                """
                UPDATE match_suggestions
                SET status = 'rejected'
                WHERE id = ?
                """,
                (int(suggestion_id),),
            )
            conn.commit()
            return "Match rejected."

        if action != "approve":
            raise ValueError("Invalid review action.")

        allocation = parse_money(amount)

        invoice = conn.execute(
            "SELECT amount FROM invoices WHERE id = ?",
            (invoice_id,),
        ).fetchone()

        payment = conn.execute(
            "SELECT amount FROM payments WHERE id = ?",
            (payment_id,),
        ).fetchone()

        if invoice is None or payment is None:
            raise ValueError("Invoice or payment not found.")

        invoice_used = sum(
            (
                Decimal(row[0])
                for row in conn.execute(
                    """
                    SELECT allocated_amount FROM allocations
                    WHERE invoice_id = ?
                    """,
                    (invoice_id,),
                )
            ),
            Decimal("0"),
        )

        payment_used = sum(
            (
                Decimal(row[0])
                for row in conn.execute(
                    """
                    SELECT allocated_amount FROM allocations
                    WHERE payment_id = ?
                    """,
                    (payment_id,),
                )
            ),
            Decimal("0"),
        )

        if allocation > Decimal(invoice[0]) - invoice_used:
            raise ValueError("Amount exceeds the current invoice balance.")

        if allocation > Decimal(payment[0]) - payment_used:
            raise ValueError("Amount exceeds the current payment balance.")

        existing = conn.execute(
            """
            SELECT id, allocated_amount
            FROM allocations
            WHERE invoice_id = ? AND payment_id = ?
            """,
            (invoice_id, payment_id),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE allocations
                SET allocated_amount = ?
                WHERE id = ?
                """,
                (
                    str(Decimal(existing[1]) + allocation),
                    existing[0],
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO allocations (
                    invoice_id, payment_id, allocated_amount
                )
                VALUES (?, ?, ?)
                """,
                (invoice_id, payment_id, str(allocation)),
            )

        conn.execute(
            """
            UPDATE match_suggestions
            SET status = 'confirmed'
            WHERE id = ?
            """,
            (int(suggestion_id),),
        )

        conn.commit()
        return "Match approved and allocation saved."

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def run_integrity_checks():
    """Read-only diagnostics using Decimal for amount comparisons."""
    issues = []

    with db.get_connection() as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchall()

        for row in integrity:
            if row[0] != "ok":
                issues.append(f"SQLite integrity: {row[0]}")

        for row in conn.execute("PRAGMA foreign_key_check"):
            issues.append(f"Foreign-key issue: {tuple(row)}")

        invoices = dict(
            conn.execute("SELECT id, amount FROM invoices").fetchall()
        )
        payments = dict(
            conn.execute("SELECT id, amount FROM payments").fetchall()
        )
        allocations = conn.execute(
            """
            SELECT id, invoice_id, payment_id, allocated_amount
            FROM allocations
            """
        ).fetchall()

    def read_amount(value, label):
        try:
            result = Decimal(str(value))
            if not result.is_finite() or result <= 0:
                raise ValueError()
            if result != result.quantize(CENT):
                raise ValueError()
            return result
        except (InvalidOperation, ValueError):
            issues.append(f"Invalid amount in {label}.")
            return None

    invoice_totals = {
        key: read_amount(value, f"invoice #{key}")
        for key, value in invoices.items()
    }

    payment_totals = {
        key: read_amount(value, f"payment #{key}")
        for key, value in payments.items()
    }

    invoice_used = {}
    payment_used = {}

    for allocation_id, invoice_id, payment_id, value in allocations:
        amount = read_amount(value, f"allocation #{allocation_id}")

        if amount is None:
            continue

        invoice_used[invoice_id] = (
            invoice_used.get(invoice_id, Decimal("0")) + amount
        )
        payment_used[payment_id] = (
            payment_used.get(payment_id, Decimal("0")) + amount
        )

    for key, amount in invoice_totals.items():
        if amount is not None and invoice_used.get(
            key, Decimal("0")
        ) > amount:
            issues.append(f"Invoice #{key} is overallocated.")

    for key, amount in payment_totals.items():
        if amount is not None and payment_used.get(
            key, Decimal("0")
        ) > amount:
            issues.append(f"Payment #{key} is overallocated.")

    return issues