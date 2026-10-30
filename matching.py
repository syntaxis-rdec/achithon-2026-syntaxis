
import pandas as pd
from decimal import Decimal
from rapidfuzz import fuzz


def suggest_matches(invoices, payments):
    suggestions = []

    for _, invoice in invoices.iterrows():
        for _, payment in payments.iterrows():

            score = 0
            reasons = []

            # 1. Compare customer names
            invoice_name = str(invoice["customer_name"]).strip().lower()
            payment_name = str(payment["customer_name"]).strip().lower()

            name_score = fuzz.ratio(invoice_name, payment_name)

            if name_score >= 90:
                score += 35
                reasons.append("Customer names are very similar")
            elif name_score >= 75:
                score += 25
                reasons.append("Customer names are somewhat similar")

            # 2. Compare reference numbers
            invoice_ref = str(invoice.get("reference", "")).strip()
            payment_ref = str(payment.get("reference", "")).strip()

            if invoice_ref and payment_ref and invoice_ref == payment_ref:
                score += 45
                reasons.append("Reference numbers match")

            # 3. Compare amounts
            invoice_amount = Decimal(str(invoice["amount"]))
            payment_amount = Decimal(str(payment["amount"]))

            if invoice_amount == payment_amount:
                score += 15
                reasons.append("Amounts match exactly")

            # 4. Compare dates
            invoice_date = pd.to_datetime(
                invoice["invoice_date"], errors="coerce"
            )
            payment_date = pd.to_datetime(
                payment["payment_date"], errors="coerce"
            )

            if pd.notna(invoice_date) and pd.notna(payment_date):
                days_difference = abs(
                    (payment_date - invoice_date).days
                )

                if days_difference <= 7:
                    score += 5
                    reasons.append("Dates are within 7 days")

            # Amount alone is not enough to suggest a match
            if score >= 40:
                suggestions.append({
                    "invoice_id": invoice["invoice_id"],
                    "payment_id": payment["payment_id"],
                    "score": score,
                    "explanation": "; ".join(reasons),
                    "status": "pending"
                })

    suggestions.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    return suggestions


if __name__ == "__main__":
    invoices = pd.read_csv("data/invoices.csv").fillna("")
    payments = pd.read_csv("data/payments.csv").fillna("")

    results = suggest_matches(invoices, payments)

    print("\nMATCH SUGGESTIONS\n")

    if not results:
        print("No possible matches found.")

    for result in results:
        print(result)
