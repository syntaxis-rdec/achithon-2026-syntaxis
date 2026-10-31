
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

