
import pandas as pd

INVOICE_COLUMNS = [
    "invoice_id",
    "customer_name",
    "amount",
    "invoice_date",
    "reference"
]

PAYMENT_COLUMNS = [
    "payment_id",
    "customer_name",
    "amount",
    "payment_date",
    "reference",
    "description"
]


def validate_file(df, required_columns):
    errors = []

    # Check required columns
    missing = [
        col for col in required_columns
        if col not in df.columns
    ]

    if missing:
        errors.append(
            f"Missing columns: {', '.join(missing)}"
        )
        return errors

    # Check empty required values
    for col in required_columns:
        if col in ["reference", "description"]:
            continue

        if df[col].isna().any() or (
            df[col].astype(str).str.strip() == ""
        ).any():
            errors.append(
                f"Some rows have empty values in '{col}'."
            )

    # Check amount values
    if "amount" in df.columns:
        amounts = pd.to_numeric(
            df["amount"], errors="coerce"
        )

        if amounts.isna().any():
            errors.append("Some amounts are not valid numbers.")

        elif (amounts <= 0).any():
            errors.append("Amounts must be greater than zero.")

    # Check duplicate IDs
    for col in ["invoice_id", "payment_id"]:
        if col in df.columns and df[col].duplicated().any():
            errors.append(f"Duplicate values found in '{col}'.")

    return errors
