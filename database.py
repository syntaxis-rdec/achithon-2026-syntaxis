
import sqlite3
from pathlib import Path

# Database file location
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "reconciliation.db"


def get_connection():
    """Connect to the SQLite database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DB_PATH)
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


def create_tables():
    """Create all required database tables."""

    with get_connection() as conn:

        # Store invoice records
        conn.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id TEXT UNIQUE NOT NULL,
                customer_name TEXT NOT NULL,
                amount TEXT NOT NULL,
                invoice_date TEXT,
                reference TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Store payment records
        conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_id TEXT UNIQUE NOT NULL,
                customer_name TEXT,
                amount TEXT NOT NULL,
                payment_date TEXT,
                reference TEXT,
                description TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Store suggested matches and review decisions
        conn.execute("""
            CREATE TABLE IF NOT EXISTS match_suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL,
                payment_id INTEGER NOT NULL,
                score REAL NOT NULL,
                explanation TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (invoice_id) REFERENCES invoices(id),
                FOREIGN KEY (payment_id) REFERENCES payments(id),
                UNIQUE(invoice_id, payment_id)
            )
        """)

        # Store confirmed payment allocations
        conn.execute("""
            CREATE TABLE IF NOT EXISTS allocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL,
                payment_id INTEGER NOT NULL,
                allocated_amount TEXT NOT NULL,
                confirmed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (invoice_id) REFERENCES invoices(id),
                FOREIGN KEY (payment_id) REFERENCES payments(id),
                UNIQUE(invoice_id, payment_id)
            )
        """)

    print("Database and tables created successfully!")


def save_match_suggestions(suggestions):
    with get_connection() as conn:
        for item in suggestions:
            invoice = conn.execute(
                "SELECT id FROM invoices WHERE invoice_id = ?",
                (item["invoice_id"],)
            ).fetchone()

            payment = conn.execute(
                "SELECT id FROM payments WHERE payment_id = ?",
                (item["payment_id"],)
            ).fetchone()

            if invoice is None or payment is None:
                continue

            conn.execute("""
                INSERT INTO match_suggestions
                (invoice_id, payment_id, score, explanation, status)
                VALUES (?, ?, ?, ?, 'pending')
                ON CONFLICT(invoice_id, payment_id)
                DO UPDATE SET
                    score = excluded.score,
                    explanation = excluded.explanation
                WHERE match_suggestions.status = 'pending'
            """, (
                invoice[0],
                payment[0],
                item["score"],
                item["explanation"]
            ))


def get_match_suggestions():
    with get_connection() as conn:
        return conn.execute("""
            SELECT
                ms.id,
                i.invoice_id,
                p.payment_id,
                ms.score,
                ms.explanation,
                ms.status
            FROM match_suggestions ms
            JOIN invoices i ON i.id = ms.invoice_id
            JOIN payments p ON p.id = ms.payment_id
            ORDER BY ms.score DESC
        """).fetchall()



def save_invoices(df):
    from decimal import Decimal

    with get_connection() as conn:
        existing_ids = {
            row[0] for row in conn.execute(
                "SELECT invoice_id FROM invoices"
            ).fetchall()
        }

        rows = []
        skipped = 0
        seen_ids = set()

        for _, row in df.iterrows():
            invoice_id = str(row["invoice_id"]).strip()

            if invoice_id in existing_ids or invoice_id in seen_ids:
                skipped += 1
                continue

            amount = Decimal(str(row["amount"])).quantize(
                Decimal("0.01")
            )

            if not amount.is_finite() or amount <= 0:
                raise ValueError("Invoice amount must be positive.")

            if not invoice_id:
                raise ValueError("Invoice ID cannot be empty.")

            seen_ids.add(invoice_id)

            rows.append((
                invoice_id,
                str(row["customer_name"]).strip(),
                str(amount),
                str(row["invoice_date"]),
                str(row.get("reference", ""))
            ))

        if rows:
            conn.executemany("""
                INSERT INTO invoices
                (invoice_id, customer_name, amount, invoice_date, reference)
                VALUES (?, ?, ?, ?, ?)
            """, rows)

        return {
            "saved": len(rows),
            "skipped": skipped
        }


def save_payments(df):
    from decimal import Decimal

    with get_connection() as conn:
        existing_ids = {
            row[0] for row in conn.execute(
                "SELECT payment_id FROM payments"
            ).fetchall()
        }

        rows = []
        skipped = 0
        seen_ids = set()

        for _, row in df.iterrows():
            payment_id = str(row["payment_id"]).strip()

            if payment_id in existing_ids or payment_id in seen_ids:
                skipped += 1
                continue

            amount = Decimal(str(row["amount"])).quantize(
                Decimal("0.01")
            )

            if not amount.is_finite() or amount <= 0:
                raise ValueError("Payment amount must be positive.")

            if not payment_id:
                raise ValueError("Payment ID cannot be empty.")

            seen_ids.add(payment_id)

            rows.append((
                payment_id,
                str(row.get("customer_name", "")).strip(),
                str(amount),
                str(row["payment_date"]),
                str(row.get("reference", "")),
                str(row.get("description", ""))
            ))

        if rows:
            conn.executemany("""
                INSERT INTO payments
                (payment_id, customer_name, amount, payment_date,
                 reference, description)
                VALUES (?, ?, ?, ?, ?, ?)
            """, rows)

        return {
            "saved": len(rows),
            "skipped": skipped
        }

def confirm_allocation(invoice_id, payment_id, amount):
    from decimal import Decimal, InvalidOperation

    try:
        allocation = Decimal(str(amount)).quantize(
            Decimal("0.01")
        )
    except InvalidOperation:
        raise ValueError("Invalid allocation amount.")

    if not allocation.is_finite() or allocation <= 0:
        raise ValueError("Allocation must be positive.")

    conn = get_connection()

    try:
        conn.execute("BEGIN IMMEDIATE")

        invoice = conn.execute(
            "SELECT amount FROM invoices WHERE id = ?",
            (invoice_id,)
        ).fetchone()

        payment = conn.execute(
            "SELECT amount FROM payments WHERE id = ?",
            (payment_id,)
        ).fetchone()

        if invoice is None or payment is None:
            raise ValueError("Invoice or payment not found.")

        invoice_used = conn.execute(
            "SELECT allocated_amount FROM allocations WHERE invoice_id = ?",
            (invoice_id,)
        ).fetchall()

        payment_used = conn.execute(
            "SELECT allocated_amount FROM allocations WHERE payment_id = ?",
            (payment_id,)
        ).fetchall()

        invoice_remaining = Decimal(invoice[0]) - sum(
            (Decimal(x[0]) for x in invoice_used), Decimal("0")
        )

        payment_remaining = Decimal(payment[0]) - sum(
            (Decimal(x[0]) for x in payment_used), Decimal("0")
        )

        if allocation > invoice_remaining:
            raise ValueError("Allocation exceeds invoice balance.")

        if allocation > payment_remaining:
            raise ValueError("Allocation exceeds remaining payment.")


        existing = conn.execute("""
            SELECT id, allocated_amount
            FROM allocations
            WHERE invoice_id = ? AND payment_id = ?
        """, (invoice_id, payment_id)).fetchone()

        if existing:
            allocation_id, previous_amount = existing

            new_total = Decimal(previous_amount) + allocation

            conn.execute("""
                UPDATE allocations
                SET allocated_amount = ?
                WHERE id = ?
            """, (str(new_total), allocation_id))

        else:
            conn.execute("""
                INSERT INTO allocations
                (invoice_id, payment_id, allocated_amount)
                VALUES (?, ?, ?)
            """, (invoice_id, payment_id, str(allocation)))


        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


from decimal import Decimal


def get_pending_reviews():
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT
                ms.id,
                ms.invoice_id,
                ms.payment_id,
                i.invoice_id,
                p.payment_id,
                ms.score,
                ms.explanation,
                i.amount,
                p.amount
            FROM match_suggestions ms
            JOIN invoices i ON i.id = ms.invoice_id
            JOIN payments p ON p.id = ms.payment_id
            WHERE ms.status = 'pending'
            ORDER BY ms.score DESC
        """).fetchall()

        reviews = []

        for row in rows:
            invoice_used = conn.execute("""
                SELECT allocated_amount FROM allocations
                WHERE invoice_id = ?
            """, (row[1],)).fetchall()

            payment_used = conn.execute("""
                SELECT allocated_amount FROM allocations
                WHERE payment_id = ?
            """, (row[2],)).fetchall()

            invoice_remaining = Decimal(row[7]) - sum(
                (Decimal(x[0]) for x in invoice_used),
                Decimal("0")
            )

            payment_remaining = Decimal(row[8]) - sum(
                (Decimal(x[0]) for x in payment_used),
                Decimal("0")
            )

            reviews.append({
                "suggestion_id": row[0],
                "invoice_db_id": row[1],
                "payment_db_id": row[2],
                "invoice_id": row[3],
                "payment_id": row[4],
                "score": row[5],
                "explanation": row[6],
                "invoice_remaining": invoice_remaining,
                "payment_remaining": payment_remaining
            })

        return reviews


def review_match(suggestion_id, action, amount=None):
    conn = get_connection()

    try:
        conn.execute("BEGIN IMMEDIATE")

        suggestion = conn.execute("""
            SELECT invoice_id, payment_id, status
            FROM match_suggestions
            WHERE id = ?
        """, (suggestion_id,)).fetchone()

        if suggestion is None:
            raise ValueError("Suggestion not found.")

        invoice_id, payment_id, status = suggestion

        if status != "pending":
            raise ValueError("This suggestion has already been reviewed.")

        if action == "reject":
            conn.execute("""
                UPDATE match_suggestions
                SET status = 'rejected'
                WHERE id = ?
            """, (suggestion_id,))

            conn.commit()
            return "Match rejected."

        if action != "approve":
            raise ValueError("Invalid review action.")

        allocation = Decimal(str(amount)).quantize(
            Decimal("0.01")
        )

        if not allocation.is_finite() or allocation <= 0:
            raise ValueError("Allocation must be positive.")

        invoice = conn.execute(
            "SELECT amount FROM invoices WHERE id = ?",
            (invoice_id,)
        ).fetchone()

        payment = conn.execute(
            "SELECT amount FROM payments WHERE id = ?",
            (payment_id,)
        ).fetchone()

        invoice_used = conn.execute("""
            SELECT allocated_amount FROM allocations
            WHERE invoice_id = ?
        """, (invoice_id,)).fetchall()

        payment_used = conn.execute("""
            SELECT allocated_amount FROM allocations
            WHERE payment_id = ?
        """, (payment_id,)).fetchall()

        invoice_remaining = Decimal(invoice[0]) - sum(
            (Decimal(x[0]) for x in invoice_used),
            Decimal("0")
        )

        payment_remaining = Decimal(payment[0]) - sum(
            (Decimal(x[0]) for x in payment_used),
            Decimal("0")
        )

        if allocation > invoice_remaining:
            raise ValueError("Amount exceeds the invoice balance.")

        if allocation > payment_remaining:
            raise ValueError("Amount exceeds the remaining payment.")

        conn.execute("""
            INSERT INTO allocations
            (invoice_id, payment_id, allocated_amount)
            VALUES (?, ?, ?)
        """, (invoice_id, payment_id, str(allocation)))

        conn.execute("""
            UPDATE match_suggestions
            SET status = 'confirmed'
            WHERE id = ?
        """, (suggestion_id,))

        conn.commit()
        return "Match approved and allocation saved."

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


from decimal import Decimal


def get_invoice_balances():
    with get_connection() as conn:
        invoices = conn.execute("""
            SELECT id, invoice_id, customer_name, amount
            FROM invoices
            ORDER BY invoice_id
        """).fetchall()

        results = []

        for invoice in invoices:
            invoice_db_id, invoice_id, customer_name, amount = invoice

            allocations = conn.execute("""
                SELECT allocated_amount
                FROM allocations
                WHERE invoice_id = ?
            """, (invoice_db_id,)).fetchall()

            original_amount = Decimal(amount)

            paid_amount = sum(
                (Decimal(row[0]) for row in allocations),
                Decimal("0")
            )

            balance = original_amount - paid_amount

            if balance == 0:
                status = "Paid"
            elif paid_amount > 0:
                status = "Partially Paid"
            else:
                status = "Unpaid"

            results.append({
                "Invoice ID": invoice_id,
                "Customer": customer_name,
                "Original Amount": float(original_amount),
                "Amount Paid": float(paid_amount),
                "Remaining Balance": float(balance),
                "Status": status
            })

        return results


from decimal import Decimal


def get_payment_report():
    with get_connection() as conn:
        payments = conn.execute("""
            SELECT id, payment_id, customer_name, amount
            FROM payments
            ORDER BY payment_id
        """).fetchall()

        results = []

        for payment in payments:
            db_id, payment_id, customer, amount = payment

            allocations = conn.execute("""
                SELECT allocated_amount
                FROM allocations
                WHERE payment_id = ?
            """, (db_id,)).fetchall()

            original = Decimal(amount)

            allocated = sum(
                (Decimal(row[0]) for row in allocations),
                Decimal("0")
            )

            remaining = original - allocated

            if remaining == 0:
                status = "Fully Allocated"
            elif allocated > 0:
                status = "Partially Allocated"
            else:
                status = "Unallocated"

            results.append({
                "Payment ID": payment_id,
                "Customer": customer,
                "Payment Amount": float(original),
                "Allocated Amount": float(allocated),
                "Unallocated Amount": float(remaining),
                "Status": status
            })

        return results



def get_available_invoices():
    with get_connection() as conn:
        invoices = conn.execute("""
            SELECT id, invoice_id, customer_name
            FROM invoices
            ORDER BY invoice_id
        """).fetchall()

    balances = get_invoice_balances()

    for item in balances:
        for invoice in invoices:
            if item["Invoice ID"] == invoice[1]:
                item["invoice_db_id"] = invoice[0]
                break

    return balances




def get_available_payments():
    with get_connection() as conn:
        payments = conn.execute("""
            SELECT id, payment_id
            FROM payments
            ORDER BY payment_id
        """).fetchall()

    report = get_payment_report()

    for item in report:
        for payment in payments:
            if item["Payment ID"] == payment[1]:
                item["payment_db_id"] = payment[0]
                break

    return report


def get_allocation_history():
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT
                a.id,
                i.invoice_id,
                i.customer_name,
                p.payment_id,
                a.allocated_amount,
                a.confirmed_at
            FROM allocations a
            JOIN invoices i
                ON a.invoice_id = i.id
            JOIN payments p
                ON a.payment_id = p.id
            ORDER BY a.confirmed_at DESC, a.id DESC
        """).fetchall()

    history = []

    for row in rows:
        history.append({
            "Allocation ID": row[0],
            "Invoice ID": row[1],
            "Customer": row[2],
            "Payment ID": row[3],
            "Allocated Amount": float(row[4]),
            "Allocation Date": row[5]
        })

    return history


def get_customer_reconciliation():
    with get_connection() as conn:
        customers = conn.execute("""
            SELECT DISTINCT customer_name
            FROM invoices
            UNION
            SELECT DISTINCT customer_name
            FROM payments
            ORDER BY customer_name
        """).fetchall()

        results = []

        for row in customers:
            customer = row[0]

            invoices = conn.execute("""
                SELECT id, amount
                FROM invoices
                WHERE customer_name = ?
            """, (customer,)).fetchall()

            payments = conn.execute("""
                SELECT id, amount
                FROM payments
                WHERE customer_name = ?
            """, (customer,)).fetchall()

            total_invoiced = sum(
                (Decimal(str(item[1])) for item in invoices),
                Decimal("0")
            )

            total_received = sum(
                (Decimal(str(item[1])) for item in payments),
                Decimal("0")
            )

            # Count allocations only through the invoice customer.
            # This prevents counting the same allocation twice.
            allocated = conn.execute("""
                SELECT COALESCE(SUM(CAST(a.allocated_amount AS NUMERIC)), 0)
                FROM allocations a
                JOIN invoices i ON a.invoice_id = i.id
                WHERE i.customer_name = ?
            """, (customer,)).fetchone()[0]

            allocated = Decimal(str(allocated))

            outstanding = total_invoiced - allocated

            if outstanding < 0:
                status = "Over-allocated - Review"
            elif outstanding == 0:
                status = "Fully Paid"
            else:
                status = "Outstanding"

            results.append({
                "Customer": customer,
                "Total Invoiced": float(total_invoiced),
                "Total Payments": float(total_received),
                "Total Allocated": float(allocated),
                "Outstanding Balance": float(outstanding),
                "Status": status
            })

    return results


    return results



if __name__ == "__main__":
    create_tables()
