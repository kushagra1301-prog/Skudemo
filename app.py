import streamlit as st
import pandas as pd
from datetime import date
import io

st.set_page_config(page_title="PBU vs Current Forecast Gap Finder", layout="wide")

st.title("📦 SKU Forecast Drop-Off Finder")
st.caption(
    "Find SKUs that had forecast at PBU submission but now show zero forecast, "
    "and whose End-of-Sale (EOS) date is still in the future."
)

# ---------- 1. Upload ----------
st.header("1. Upload your file")
uploaded_file = st.file_uploader(
    "Upload Excel (.xlsx) or CSV with one row per SPU/SKU",
    type=["xlsx", "xls", "csv"],
)

if uploaded_file is None:
    st.info("Upload a file to get started.")
    st.stop()

# Read file
try:
    if uploaded_file.name.lower().endswith(".csv"):
        df = pd.read_csv(uploaded_file)
    else:
        xls = pd.ExcelFile(uploaded_file)
        sheet = st.selectbox("Select sheet", xls.sheet_names)
        df = pd.read_excel(uploaded_file, sheet_name=sheet)
except Exception as e:
    st.error(f"Could not read file: {e}")
    st.stop()

st.success(f"Loaded {len(df):,} rows and {len(df.columns)} columns.")
with st.expander("Preview data (first 20 rows)"):
    st.dataframe(df.head(20), use_container_width=True)

all_columns = list(df.columns)

# ---------- 2. Column mapping ----------
st.header("2. Map your columns")

col1, col2 = st.columns(2)
with col1:
    sku_col = st.selectbox("SKU / SPU_SKU column", all_columns)
    eos_col = st.selectbox("EOS date column", all_columns)
with col2:
    pbu_cols = st.multiselect(
        "PBU submission forecast column(s) — select all periods, they'll be summed",
        all_columns,
    )
    current_cols = st.multiselect(
        "Current forecast column(s) — select all periods, they'll be summed",
        all_columns,
    )

history_cols = st.multiselect(
    "Optional: Last 6 months actuals/history column(s) — shown for context on flagged SKUs "
    "(select in chronological order, e.g. 6 months ago → last month)",
    all_columns,
)

st.subheader("Options")
opt1, opt2 = st.columns(2)
with opt1:
    as_of_date = st.date_input("Compare EOS against this date", value=date.today())
with opt2:
    treat_blank_as_zero = st.checkbox("Treat blank/missing forecast values as 0", value=True)

if not pbu_cols or not current_cols:
    st.warning("Select at least one PBU forecast column and one Current forecast column to continue.")
    st.stop()

# ---------- 3. Compute ----------
st.header("3. Results")

work = df.copy()

def to_numeric_sum(frame, cols):
    sub = frame[cols].apply(pd.to_numeric, errors="coerce")
    if treat_blank_as_zero:
        sub = sub.fillna(0)
    return sub.sum(axis=1, skipna=True)

work["_PBU_Total"] = to_numeric_sum(work, pbu_cols)
work["_Current_Total"] = to_numeric_sum(work, current_cols)
work["_EOS_Date"] = pd.to_datetime(work[eos_col], errors="coerce")
if history_cols:
    work["_History_Total"] = to_numeric_sum(work, history_cols)

as_of_ts = pd.Timestamp(as_of_date)

mask = (
    (work["_Current_Total"] <= 0)
    & (work["_PBU_Total"] > 0)
    & (work["_EOS_Date"].notna())
    & (work["_EOS_Date"] > as_of_ts)
)

result = work.loc[mask].copy()

# Friendly output columns: original SKU/EOS + history + computed totals + original mapped cols
display_cols = [sku_col, eos_col] + history_cols + pbu_cols + current_cols
display_cols += ["_History_Total"] if history_cols else []
display_cols += ["_PBU_Total", "_Current_Total"]
display_cols = list(dict.fromkeys(display_cols))  # de-dupe, keep order
result_display = result[display_cols].rename(
    columns={
        "_PBU_Total": "PBU Forecast (sum)",
        "_Current_Total": "Current Forecast (sum)",
        "_History_Total": "Last 6 Months Actuals (sum)",
    }
)

m1, m2, m3 = st.columns(3)
m1.metric("Total SKUs in file", f"{len(df):,}")
m1.metric if False else None
m2.metric("SKUs with EOS after as-of date", f"{int((work['_EOS_Date'] > as_of_ts).sum()):,}")
m3.metric("⚠️ SKUs flagged (forecast dropped to zero)", f"{len(result_display):,}")

if result_display.empty:
    st.success("No SKUs match the criteria — nothing dropped to zero unexpectedly.")
else:
    st.dataframe(result_display, use_container_width=True)

    # Download buttons
    csv_bytes = result_display.to_csv(index=False).encode("utf-8")
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        result_display.to_excel(writer, index=False, sheet_name="Flagged SKUs")
    excel_bytes = buffer.getvalue()

    d1, d2 = st.columns(2)
    with d1:
        st.download_button(
            "⬇️ Download as CSV",
            data=csv_bytes,
            file_name="flagged_zero_forecast_skus.csv",
            mime="text/csv",
        )
    with d2:
        st.download_button(
            "⬇️ Download as Excel",
            data=excel_bytes,
            file_name="flagged_zero_forecast_skus.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    # ---------- Last 6 months trend for flagged SKUs ----------
    if history_cols:
        st.subheader("📈 Last 6 months actuals — flagged SKUs")
        st.caption(
            "Shows actual history for each flagged SKU, in the column order you selected above. "
            "Useful for spotting whether the SKU was already trending down before forecast hit zero."
        )
        trend = result[[sku_col] + history_cols].copy()
        trend[history_cols] = trend[history_cols].apply(pd.to_numeric, errors="coerce")
        if treat_blank_as_zero:
            trend[history_cols] = trend[history_cols].fillna(0)
        trend = trend.set_index(sku_col)
        st.line_chart(trend.T)

st.divider()
st.caption(
    "Logic: flags a SKU when (Current Forecast total ≤ 0) AND (PBU Forecast total > 0) "
    "AND (EOS date is after the as-of date). Adjust the as-of date or zero-handling option above as needed."
)
