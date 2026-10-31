
from html import escape
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
import json
import sqlite3

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import database as db

from matching import suggest_matches
from validation import (
    validate_file,
    INVOICE_COLUMNS,
    PAYMENT_COLUMNS,
)
from finance_features import (
    initialize_features,
    get_activity,
    get_invoice_age_report,
    load_matching_data,
    parse_money,
    review_match,
    run_integrity_checks,
)


st.set_page_config(
    page_title="ReconFlow | Intelligence Workspace",
    page_icon="◈",
    layout="wide",
)

try:
    initialize_features()
except Exception as exc:
    st.error(f"Initialization failed: {exc}")
    st.stop()


# -------------------- DESIGN --------------------

st.html("""
<style>
.stApp {
    background:
        radial-gradient(
            ellipse at 90% 0%,
            rgba(124, 92, 255, .13),
            transparent 38%
        ),
        #0B1020;
}
.block-container {
    max-width: 1500px;
    padding-top: 2rem;
    padding-bottom: 3rem;
}
h1, h2, h3 { letter-spacing: -.035em; }

.brand {
    font-size: 29px;
    font-weight: 850;
    color: #F5F6FF;
    letter-spacing: -.06em;
}
.brand span { color: #A99AFF; }
.brand-sub {
    color: #8895B5;
    font-size: 10px;
    letter-spacing: .2em;
    margin: 4px 0 26px;
}
.hero {
    padding: 30px;
    margin-bottom: 24px;
    border: 1px solid rgba(167, 146, 255, .22);
    border-radius: 24px;
    background: linear-gradient(
        115deg, #151E38, #25224B 65%, #443477
    );
    box-shadow: 0 20px 55px rgba(0,0,0,.16);
}
.eyebrow {
    color: #BDB0FF;
    letter-spacing: .17em;
    font-size: 10px;
    font-weight: 750;
}
.hero h1 {
    color: #FFFFFF;
    font-size: clamp(28px, 3vw, 42px);
    margin: 10px 0;
    padding: 0;
}
.hero p {
    color: #BBC5E0;
    font-size: 14px;
    margin: 0;
    line-height: 1.8;
}
.kpi {
    background: linear-gradient(145deg, #161F35, #121A2E);
    border: 1px solid #27324B;
    border-radius: 18px;
    padding: 22px;
    margin-bottom: 18px;
    min-height: 145px;
}
.kpi-label {
    color: #98A7C7;
    font-size: 11px;
    letter-spacing: .08em;
}
.kpi-value {
    font-size: clamp(22px, 2.1vw, 34px);
    font-weight: 800;
    color: #F5F7FF;
    letter-spacing: -.05em;
    margin: 12px 0 5px;
    overflow-wrap: anywhere;
}
.kpi-note { color: #8190B2; font-size: 12px; }
.sidebar-note {
    border: 1px solid #303651;
    background: #171C32;
    border-radius: 14px;
    padding: 15px;
    color: #AAB4D1;
    font-size: 12px;
    line-height: 1.8;
}
.footer {
    color: #7483A5;
    text-align: center;
    margin-top: 32px;
    font-size: 12px;
}
@media(max-width:700px) {
    .hero { padding: 22px; }
    .block-container { padding-top: 1rem; }
}
</style>
""")


# -------------------- HELPERS --------------------

def hero(title, subtitle):
    st.html(
        f"""
        <div class="hero">
            <div class="eyebrow">RECONFLOW / INTELLIGENCE WORKSPACE</div>
            <h1>{escape(title)}</h1>
            <p>{escape(subtitle)}</p>
        </div>
        """
    )


def money(value):
    return f"₹{float(value):,.2f}"


def total(df, column):
    if df.empty or column not in df:
        return 0.0
    return pd.to_numeric(
        df[column], errors="coerce"
    ).fillna(0).sum()


def card(label, value, note):
    st.html(
        f"""
        <div class="kpi">
            <div class="kpi-label">{escape(label)}</div>
            <div class="kpi-value">{escape(str(value))}</div>
            <div class="kpi-note">{escape(note)}</div>
        </div>
        """
    )


def table(df):
    st.dataframe(df, hide_index=True, use_container_width=True)


def finish(message):
    st.session_state["flash"] = str(message)
    st.rerun()


def chart(fig):
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#B9C5E2"),
        margin=dict(l=10, r=10, t=30, b=10),
        legend_title_text="",
    )
    st.plotly_chart(
        fig,
        use_container_width=True,
        config={"displaylogo": False},
    )


def filter_rows(df, query):
    if df.empty or not query.strip():
        return df

    mask = df.astype(str).apply(
        lambda col: col.str.contains(
            query.strip(),
            case=False,
            regex=False,
            na=False,
        )
    ).any(axis=1)

    return df[mask]


def upload_panel(title, required_columns, save_function, key):
    with st.container(border=True):
        st.subheader(title)
        st.caption("Validate → preview → save")

        with st.expander("Required columns"):
            st.code(
                ", ".join(map(str, required_columns)),
                language=None,
            )

        uploaded = st.file_uploader(
            "Choose a CSV",
            type=["csv"],
            key=key,
        )

        if uploaded is None:
            st.info("Upload a file to begin.")
            return

        try:
            # Preserve IDs such as INV-001 and leading-zero references.
            df = pd.read_csv(uploaded, dtype=str).fillna("")
            errors = validate_file(df, required_columns)

            if errors:
                for error in errors:
                    st.error(str(error))
                return

            if df.empty:
                st.warning("This file contains no records.")
                return

            st.success(f"{len(df):,} records passed validation.")
            table(df)

            if st.button(
                f"Save {title.lower()}",
                key=f"save_{key}",
                type="primary",
                use_container_width=True,
            ):
                try:
                    save_function(df)
                    finish(f"{len(df):,} {title.lower()} saved.")
                except sqlite3.IntegrityError:
                    st.error(
                        "Upload rejected: duplicate IDs or another "
                        "database constraint violation. "
                        "No rows from this upload were committed."
                    )
                except Exception as exc:
                    st.error(f"Save failed: {exc}")

        except Exception as exc:
            st.error(f"Could not read or validate this file: {exc}")


def report_bundle(invoices, payments):
    output = BytesIO()

    with ZipFile(output, "w", ZIP_DEFLATED) as bundle:
        bundle.writestr(
            "invoice_balances.csv",
            invoices.to_csv(index=False).encode("utf-8-sig"),
        )
        bundle.writestr(
            "payment_reconciliation.csv",
            payments.to_csv(index=False).encode("utf-8-sig"),
        )
        bundle.writestr(
            "recent_activity.csv",
            get_activity(1000).to_csv(
                index=False
            ).encode("utf-8-sig"),
        )
        bundle.writestr(
            "README.txt",
            "ReconFlow report bundle\n"
            "Activity contains at most the latest 1000 events.\n"
            "Activity logging starts when the upgrade is installed.\n"
            "Invoice age is not an overdue calculation.\n",
        )

    return output.getvalue()


# -------------------- NAVIGATION --------------------

with st.sidebar:
    st.html("""
        <div class="brand">◈ Recon<span>Flow</span></div>
        <div class="brand-sub">FINANCIAL INTELLIGENCE</div>
    """)

    page = st.radio(
        "Navigation",
        [
            "Overview",
            "Upload studio",
            "Matching engine",
            "Review queue",
            "Allocate payment",
            "Customer explorer",
            "Reports",
            "Activity & checks",
            "Command center",
        ],
        label_visibility="collapsed",
    )

    st.divider()

    st.html("""
        <div class="sidebar-note">
            <b>Review-first reconciliation</b><br>
            Suggestions assist your decision.<br>
            Allocations change balances.<br>
            Activity records future changes.
        </div>
    """)

    st.caption("SQLite storage · INR")


if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))


# Load current report data on each rerun.
# Do not cache financial balances without an invalidation strategy.
try:
    invoices = pd.DataFrame(db.get_invoice_balances())
    payments = pd.DataFrame(db.get_payment_report())
except Exception as exc:
    st.error(f"Could not load financial data: {exc}")
    st.stop()


# -------------------- OVERVIEW --------------------

if page == "Overview":
    hero(
        "Make every payment make sense.",
        "Reconciliation, customer exposure, and financial visibility "
        "in one focused workspace.",
    )

    invoiced = total(invoices, "Original Amount")
    allocated = total(invoices, "Amount Paid")
    outstanding = total(invoices, "Remaining Balance")
    available = total(payments, "Unallocated Amount")

    cols = st.columns(4)

    values = [
        ("TOTAL INVOICED", money(invoiced),
         f"{len(invoices):,} invoices"),
        ("ALLOCATED TO INVOICES", money(allocated),
         "Confirmed allocations"),
        ("OUTSTANDING", money(outstanding),
         "Remaining invoice balance"),
        ("AVAILABLE PAYMENTS", money(available),
         "Not yet allocated"),
    ]

    for col, values_for_card in zip(cols, values):
        with col:
            card(*values_for_card)

    left, right = st.columns([1, 1.25])

    with left:
        with st.container(border=True):
            st.subheader("Invoice reconciliation")

            if invoiced > 0:
                fig = go.Figure(
                    go.Pie(
                        labels=["Allocated", "Outstanding"],
                        values=[allocated, outstanding],
                        hole=0.76,
                        marker=dict(
                            colors=["#9A83FF", "#27324B"]
                        ),
                        textinfo="none",
                        hovertemplate=(
                            "%{label}<br>₹%{value:,.2f}<extra></extra>"
                        ),
                    )
                )

                fig.update_layout(
                    height=310,
                    annotations=[
                        dict(
                            text=f"{allocated / invoiced:.1%}",
                            x=0.5,
                            y=0.5,
                            showarrow=False,
                            font=dict(size=34, color="#F5F7FF"),
                        )
                    ],
                )

                chart(fig)
            else:
                st.info("Upload invoices to populate this chart.")

    with right:
        with st.container(border=True):
            st.subheader("Largest customer balances")

            if not invoices.empty:
                exposure = (
                    invoices.groupby("Customer", as_index=False)
                    ["Remaining Balance"].sum()
                )
                exposure = exposure[
                    exposure["Remaining Balance"] > 0
                ].nlargest(7, "Remaining Balance")

                if not exposure.empty:
                    chart(
                        px.bar(
                            exposure,
                            x="Remaining Balance",
                            y="Customer",
                            orientation="h",
                            color_discrete_sequence=["#9A83FF"],
                        )
                    )
                else:
                    st.success("All invoice balances are cleared.")
            else:
                st.info("Customer exposure appears after upload.")

    with st.container(border=True):
        st.subheader("Outstanding invoice age")
        st.caption(
            "Age is measured from invoice date, not payment due date. "
            "Unknown and future-dated invoices remain separate."
        )

        aged = get_invoice_age_report()

        if not aged.empty:
            aged = aged[aged["Remaining Balance"] > 0]

            if not aged.empty:
                summary = aged.groupby(
                    "Age band", as_index=False
                )["Remaining Balance"].sum()

                chart(
                    px.bar(
                        summary,
                        x="Age band",
                        y="Remaining Balance",
                        category_orders={
                            "Age band": [
                                "0–30 days",
                                "31–60 days",
                                "61–90 days",
                                "91+ days",
                                "Unknown date",
                                "Future dated",
                            ]
                        },
                        color_discrete_sequence=["#47D7C2"],
                    )
                )
            else:
                st.info("No outstanding invoices.")
        else:
            st.info("No invoice records yet.")

# -------------------- UPLOADS --------------------

elif page == "Upload studio":
    hero(
        "Clean inputs. Confident results.",
        "Validate your source files and inspect every upload "
        "before it enters the reconciliation workflow.",
    )

    st.caption(
        "CSV values are loaded as text to preserve IDs and references. "
        "Your validation module should explicitly parse numeric/date fields."
    )

    left, right = st.columns(2)

    with left:
        upload_panel(
            "Invoices",
            INVOICE_COLUMNS,
            db.save_invoices,
            "invoice_upload",
        )

    with right:
        upload_panel(
            "Payments",
            PAYMENT_COLUMNS,
            db.save_payments,
            "payment_upload",
        )


# -------------------- MATCHING --------------------

elif page == "Matching engine":
    hero(
        "Find connections. Keep control.",
        "Generate explainable suggestions with your current matching "
        "engine. Nothing is allocated until you approve it.",
    )

    with st.container(border=True):
        st.subheader("Generate suggestions")
        st.caption(
            "Reviewed suggestions keep their existing decision. "
            "Pending pairs can have their scores refreshed."
        )

        if st.button(
            "Run matching engine",
            type="primary",
            use_container_width=True,
        ):
            try:
                with st.spinner("Analyzing your records..."):
                    source_invoices, source_payments = (
                        load_matching_data()
                    )

                    if source_invoices.empty or source_payments.empty:
                        st.warning(
                            "Upload invoices and payments first."
                        )
                    else:
                        suggestions = suggest_matches(
                            source_invoices,
                            source_payments,
                        )
                        db.save_match_suggestions(suggestions)

                        finish(
                            f"Engine returned {len(suggestions):,} "
                            "suggestions. Pending matches refreshed."
                        )
            except Exception as exc:
                st.error(f"Matching failed: {exc}")

    saved = db.get_match_suggestions()

    if saved:
        results = pd.DataFrame(
            saved,
            columns=[
                "ID", "Invoice ID", "Payment ID",
                "Score", "Explanation", "Status",
            ],
        )

        left, right = st.columns([2, 1])

        with left:
            query = st.text_input("Search suggestions")

        with right:
            status = st.selectbox(
                "Status",
                ["All"] + sorted(
                    results["Status"].astype(str).unique().tolist()
                ),
            )

        filtered = filter_rows(results, query)

        if status != "All":
            filtered = filtered[filtered["Status"] == status]

        table(filtered)

    else:
        st.info("No matching suggestions yet.")


# -------------------- REVIEWS --------------------

elif page == "Review queue":
    hero(
        "Your judgment. Supported by evidence.",
        "Inspect matching explanations and current balances "
        "before approving a financial allocation.",
    )

    pending = db.get_pending_reviews()

    minimum_score = st.slider(
        "Minimum matching score",
        min_value=0,
        max_value=100,
        value=0,
    )

    visible = [
        item for item in pending
        if float(item["score"]) >= minimum_score
    ]

    st.caption(
        f"{len(visible):,} visible · {len(pending):,} pending. "
        "Scores are matching-engine scores, not calibrated probabilities."
    )

    if not visible:
        st.info("No pending suggestions match this filter.")

    for item in visible:
        with st.container(border=True):
            st.subheader(
                f"{item['invoice_id']} ↔ {item['payment_id']}"
            )

            st.write(item["explanation"])
            st.caption(f"Matching score: {item['score']}/100")

            maximum = min(
                item["invoice_remaining"],
                item["payment_remaining"],
            )

            left, right = st.columns(2)

            left.metric(
                "Invoice balance",
                money(item["invoice_remaining"]),
            )
            right.metric(
                "Payment available",
                money(item["payment_remaining"]),
            )

            with st.form(f"review_{item['suggestion_id']}"):
                amount = st.text_input(
                    "Allocation amount (₹)",
                    value=f"{max(maximum, 0):.2f}",
                    disabled=maximum <= 0,
                )

                if maximum <= 0:
                    st.warning(
                        "No amount is available. "
                        "You may still reject this suggestion."
                    )

                left, right = st.columns(2)

                with left:
                    approve = st.form_submit_button(
                        "Approve allocation",
                        type="primary",
                        disabled=maximum <= 0,
                        use_container_width=True,
                    )

                with right:
                    reject = st.form_submit_button(
                        "Reject suggestion",
                        use_container_width=True,
                    )

                if approve or reject:
                    try:
                        result = review_match(
                            item["suggestion_id"],
                            "approve" if approve else "reject",
                            amount if approve else None,
                        )
                        finish(result)
                    except Exception as exc:
                        st.error(str(exc))


# -------------------- MANUAL ALLOCATION --------------------

elif page == "Allocate payment":
    hero(
        "Allocate precisely.",
        "Apply a payment in full or in part. Current balances "
        "are checked again when the allocation is saved.",
    )

    invoice_options = {
        item["invoice_db_id"]: item
        for item in db.get_available_invoices()
        if item["Remaining Balance"] > 0
    }

    payment_options = {
        item["payment_db_id"]: item
        for item in db.get_available_payments()
        if item["Unallocated Amount"] > 0
    }

    if not invoice_options or not payment_options:
        st.info(
            "You need an outstanding invoice and an available payment."
        )

    else:
        with st.container(border=True):
            left, right = st.columns(2)

            with left:
                invoice_id = st.selectbox(
                    "Invoice",
                    list(invoice_options),
                    format_func=lambda key: (
                        f"{invoice_options[key]['Invoice ID']} · "
                        f"{invoice_options[key]['Customer']}"
                    ),
                )

            with right:
                payment_id = st.selectbox(
                    "Payment",
                    list(payment_options),
                    format_func=lambda key: (
                        f"{payment_options[key]['Payment ID']} · "
                        f"{payment_options[key]['Customer']}"
                    ),
                )

            invoice = invoice_options[invoice_id]
            payment = payment_options[payment_id]

            maximum = min(
                invoice["Remaining Balance"],
                payment["Unallocated Amount"],
            )

            left, right = st.columns(2)
            left.metric(
                "Invoice balance",
                money(invoice["Remaining Balance"]),
            )
            right.metric(
                "Payment available",
                money(payment["Unallocated Amount"]),
            )

            if str(invoice["Customer"]).strip().casefold() != (
                str(payment["Customer"]).strip().casefold()
            ):
                st.warning(
                    "Customer names differ. Verify the relationship."
                )

            with st.form(f"allocate_{invoice_id}_{payment_id}"):
                amount = st.text_input(
                    "Amount (₹)",
                    value=f"{maximum:.2f}",
                )

                acknowledged = st.checkbox(
                    "I verified the records and allocation amount."
                )

                submit = st.form_submit_button(
                    "Confirm allocation",
                    type="primary",
                    use_container_width=True,
                )

                if submit:
                    if not acknowledged:
                        st.warning("Please confirm your review.")
                    else:
                        try:
                            parsed = parse_money(amount)
                            db.confirm_allocation(
                                invoice_id,
                                payment_id,
                                str(parsed),
                            )
                            finish("Payment allocated successfully.")
                        except Exception as exc:
                            st.error(str(exc))


# -------------------- CUSTOMER EXPLORER --------------------

elif page == "Customer explorer":
    hero(
        "See the customer behind the balance.",
        "Explore invoices and recorded payments by customer name.",
    )

    names = set()

    for df in (invoices, payments):
        if not df.empty:
            names.update(df["Customer"].fillna("").astype(str))

    if not names:
        st.info("Upload records to explore customers.")

    else:
        selected = st.selectbox("Customer", sorted(names))

        customer_invoices = (
            invoices[invoices["Customer"].fillna("").astype(str)
                     == selected]
            if not invoices.empty else invoices
        )

        customer_payments = (
            payments[payments["Customer"].fillna("").astype(str)
                     == selected]
            if not payments.empty else payments
        )

        cols = st.columns(3)

        with cols[0]:
            card(
                "INVOICED",
                money(total(customer_invoices, "Original Amount")),
                f"{len(customer_invoices):,} invoices",
            )

        with cols[1]:
            card(
                "OUTSTANDING",
                money(total(customer_invoices, "Remaining Balance")),
                "Customer invoice balance",
            )

        with cols[2]:
            card(
                "AVAILABLE PAYMENTS",
                money(total(customer_payments, "Unallocated Amount")),
                "Payments recorded under this name",
            )

        st.caption(
            "Customer grouping uses exact stored names, not a verified "
            "customer identity. Cross-customer allocations can cause "
            "invoice and payment totals here to differ."
        )

        tab1, tab2 = st.tabs(["Invoices", "Payments"])

        with tab1:
            table(customer_invoices)

        with tab2:
            table(customer_payments)


