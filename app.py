
import streamlit as st
import pandas as pd
import sqlite3
from matching import suggest_matches

from database import (
    create_tables,
    save_invoices,
    save_payments,
    save_match_suggestions,
    get_match_suggestions,
    get_pending_reviews,
    review_match,
    get_invoice_balances,
    get_payment_report,
    get_available_invoices,
    get_available_payments,
    confirm_allocation,
)

from validation import (
    validate_file,
    INVOICE_COLUMNS,
    PAYMENT_COLUMNS
)

from database import (
    create_tables,
    save_invoices,
    save_payments
)

create_tables()

st.set_page_config(
    page_title="Invoice Reconciliation System",
    page_icon="📊",
    layout="wide"
)

st.title("Invoice and Payment Reconciliation System")
st.write("Upload, validate and save your financial records.")

st.divider()

# Invoice upload
st.subheader("1. Upload Invoice File")

invoice_file = st.file_uploader(
    "Choose invoice CSV",
    type=["csv"],
    key="invoice"
)

if invoice_file is not None:
    try:
        invoices = pd.read_csv(invoice_file)
        errors = validate_file(invoices, INVOICE_COLUMNS)

        if errors:
            st.error("Invoice file has errors:")
            for error in errors:
                st.write(f"- {error}")

        else:
            st.success("Invoice file is valid!")
            st.dataframe(invoices)

            if st.button("Save invoices to database"):
                try:
                    save_invoices(invoices.fillna(""))
                    st.success("Invoices saved successfully!")

                except sqlite3.IntegrityError:
                    st.error(
                        "Some invoice IDs already exist. "
                        "No records from this upload were saved."
                    )

                except Exception as e:
                    st.error(f"Could not save invoices: {e}")

    except Exception as e:
        st.error(f"Could not read invoice file: {e}")


st.divider()

# Payment upload
st.subheader("2. Upload Payment File")

payment_file = st.file_uploader(
    "Choose payment CSV",
    type=["csv"],
    key="payment"
)

if payment_file is not None:
    try:
        payments = pd.read_csv(payment_file)
        errors = validate_file(payments, PAYMENT_COLUMNS)

        if errors:
            st.error("Payment file has errors:")
            for error in errors:
                st.write(f"- {error}")

        else:
            st.success("Payment file is valid!")
            st.dataframe(payments)

            if st.button("Save payments to database"):
                try:
                    save_payments(payments.fillna(""))
                    st.success("Payments saved successfully!")

                except sqlite3.IntegrityError:
                    st.error(
                        "Some payment IDs already exist. "
                        "No records from this upload were saved."
                    )

                except Exception as e:
                    st.error(f"Could not save payments: {e}")

    except Exception as e:
        st.error(f"Could not read payment file: {e}")


st.divider()

# Matching suggestions
st.header("3. Invoice and Payment Matching")

if st.button("Generate Matching Suggestions"):
    try:
        with sqlite3.connect("data/reconciliation.db") as conn:
            invoice_data = pd.read_sql_query(
                "SELECT invoice_id, customer_name, amount, invoice_date, reference FROM invoices",
                conn
            )

            payment_data = pd.read_sql_query(
                "SELECT payment_id, customer_name, amount, payment_date, reference, description FROM payments",
                conn
            )

        suggestions = suggest_matches(invoice_data, payment_data)

        save_match_suggestions(suggestions)

        st.success(
            f"{len(suggestions)} matching suggestions generated!"
        )

    except Exception as e:
        st.error(f"Matching error: {e}")


st.subheader("Matching Results")

saved_suggestions = get_match_suggestions()

if saved_suggestions:
    results_df = pd.DataFrame(
        saved_suggestions,
        columns=[
            "ID",
            "Invoice ID",
            "Payment ID",
            "Score",
            "Explanation",
            "Status"
        ]
    )

    st.dataframe(results_df, use_container_width=True)

else:
    st.info("No matching suggestions yet. Click Generate Matching Suggestions.")



st.divider()

# Manual review section
st.header("4. Manual Match Review")

pending_reviews = get_pending_reviews()

if not pending_reviews:
    st.info("There are no pending matches to review.")

for item in pending_reviews:

    st.subheader(
        f"{item['invoice_id']}  ↔  {item['payment_id']}"
    )

    st.write(f"**Match score:** {item['score']}/100")
    st.write(f"**Reason:** {item['explanation']}")

    st.write(
        f"**Invoice balance:** ₹{item['invoice_remaining']}"
    )
    st.write(
        f"**Payment available:** ₹{item['payment_remaining']}"
    )

    max_allocation = min(
        item["invoice_remaining"],
        item["payment_remaining"]
    )

    if max_allocation <= 0:
        st.warning("No amount is available to allocate.")
        continue

    with st.form(key=f"review_{item['suggestion_id']}"):

        allocation_amount = st.text_input(
            "Amount to allocate (₹)",
            value=str(max_allocation)
        )

        approve = st.form_submit_button("Approve Match")
        reject = st.form_submit_button("Reject Match")

        if approve:
            try:
                message = review_match(
                    item["suggestion_id"],
                    "approve",
                    allocation_amount
                )
                st.success(message)
                st.rerun()

            except Exception as e:
                st.error(f"Approval failed: {e}")

        if reject:
            try:
                message = review_match(
                    item["suggestion_id"],
                    "reject"
                )
                st.success(message)
                st.rerun()

            except Exception as e:
                st.error(f"Rejection failed: {e}")


st.divider()

st.header("5. Invoice Balance Dashboard")

balances = get_invoice_balances()

if balances:
    balance_df = pd.DataFrame(balances)

    st.dataframe(
        balance_df,
        use_container_width=True,
        hide_index=True
    )

    total_invoiced = balance_df["Original Amount"].sum()
    total_paid = balance_df["Amount Paid"].sum()
    total_outstanding = balance_df["Remaining Balance"].sum()

    col1, col2, col3 = st.columns(3)

    col1.metric("Total Invoiced", f"₹{total_invoiced:,.2f}")
    col2.metric("Total Paid", f"₹{total_paid:,.2f}")
    col3.metric("Outstanding", f"₹{total_outstanding:,.2f}")

else:
    st.info("No invoices found yet.")


st.divider()

st.header("6. Payment Reconciliation Report")

payment_report = get_payment_report()

if payment_report:
    report_df = pd.DataFrame(payment_report)

    st.subheader("Payment Details")

    st.dataframe(
        report_df,
        use_container_width=True,
        hide_index=True
    )

    total_payments = report_df["Payment Amount"].sum()
    total_allocated = report_df["Allocated Amount"].sum()
    total_unallocated = report_df["Unallocated Amount"].sum()

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Total Payments",
        f"₹{total_payments:,.2f}"
    )

    col2.metric(
        "Total Allocated",
        f"₹{total_allocated:,.2f}"
    )

    col3.metric(
        "Unallocated Amount",
        f"₹{total_unallocated:,.2f}"
    )

else:
    st.info("No payment records found.")


st.divider()

st.header("7. Export Reconciliation Reports")

# Export invoice balance report
invoice_export = pd.DataFrame(get_invoice_balances())

st.download_button(
    label="Download Invoice Balance Report",
    data=invoice_export.to_csv(index=False),
    file_name="invoice_balance_report.csv",
    mime="text/csv"
)

# Export payment reconciliation report
payment_export = pd.DataFrame(get_payment_report())

st.download_button(
    label="Download Payment Reconciliation Report",
    data=payment_export.to_csv(index=False),
    file_name="payment_reconciliation_report.csv",
    mime="text/csv"
)



st.divider()

st.header("8. Advanced Payment Allocation")

available_invoices = get_available_invoices()
available_payments = get_available_payments()

invoice_options = {
    f"{item['Invoice ID']} - {item['Customer']} "
    f"(Balance: ₹{item['Remaining Balance']:,.2f})":
    item
    for item in available_invoices
    if item["Remaining Balance"] > 0
}

payment_options = {
    f"{item['Payment ID']} - {item['Customer']} "
    f"(Available: ₹{item['Unallocated Amount']:,.2f})":
    item
    for item in available_payments
    if item["Unallocated Amount"] > 0
}

if not invoice_options:
    st.info("No invoices have an outstanding balance.")

elif not payment_options:
    st.info("No payments have an unallocated amount.")

else:
    with st.form("advanced_allocation_form"):

        selected_invoice = st.selectbox(
            "Select Invoice",
            list(invoice_options.keys())
        )

        selected_payment = st.selectbox(
            "Select Payment",
            list(payment_options.keys())
        )

        allocation_amount = st.text_input(
            "Allocation Amount (₹)"
        )

        submit_allocation = st.form_submit_button(
            "Allocate Payment"
        )

        if submit_allocation:
            invoice = invoice_options[selected_invoice]
            payment = payment_options[selected_payment]

            try:
                message = confirm_allocation(
                    invoice["invoice_db_id"],
                    payment["payment_db_id"],
                    allocation_amount
                )

                st.success("Payment allocated successfully!")
                st.rerun()

            except Exception as e:
                st.error(f"Allocation failed: {e}")
