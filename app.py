"""
Interactive version - run with:

    streamlit run app.py
"""
import pandas as pd
import streamlit as st

import kpis

st.set_page_config(page_title="P2P analytics", layout="wide")


@st.cache_data
def get_data():
    d = kpis.load()
    return d, kpis.po_lines(d)


d, po_all = get_data()

# ---- sidebar filters ----
st.sidebar.header("Filters")
dmin, dmax = po_all["BEDAT"].min().date(), po_all["BEDAT"].max().date()
date_range = st.sidebar.date_input("PO date", (dmin, dmax), min_value=dmin, max_value=dmax)
sups = st.sidebar.multiselect("Supplier", sorted(po_all["NAME1"].unique()))
grps = st.sidebar.multiselect("Material group", sorted(po_all["WGBEZ"].unique()))
tol_days = st.sidebar.slider("On-time tolerance (days)", 0, 7, kpis.ON_TIME_TOLERANCE_DAYS)
tol_price = st.sidebar.slider("Price variance tolerance (%)", 0, 10,
                              int(kpis.PRICE_VAR_TOLERANCE * 100)) / 100

if isinstance(date_range, tuple) and len(date_range) == 2:
    d_from, d_to = date_range
else:  # user is still picking the second date
    d_from, d_to = dmin, dmax

po = kpis.filter_po(po_all, d_from, d_to, sups, grps)
if po.empty:
    st.warning("No PO lines for this selection.")
    st.stop()

dp = kpis.delivery_performance(d, po, tol_days)
pv = kpis.invoice_price_variance(d, po, tol_price)
s = kpis.spend_summary(po)
npr = kpis.po_without_pr(po)
lead = kpis.pr_to_po_days(d, po)["days"]

st.title("Procure-to-pay analytics")
st.caption("Sample data shaped like EKKO / EKPO / EBAN / MSEG / RSEG. All numbers are made up.")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Spend", f"€{s['spend']:,.0f}")
c2.metric("POs", f"{s['po_count']:,}")
c3.metric("OTIF", f"{dp['otif'].mean():.1%}" if len(dp) else "-")
c4.metric("PO lines without PR", f"{npr['share']:.1%}")
c5.metric("PR to PO (median)", f"{lead.median():.0f} days" if len(lead) else "-")

tab_spend, tab_del, tab_inv, tab_score = st.tabs(
    ["Spend", "Delivery", "Invoices", "Supplier scorecard"])

with tab_spend:
    left, right = st.columns(2)
    left.subheader("Monthly spend")
    left.bar_chart(kpis.monthly_spend(po))
    right.subheader("By material group")
    right.bar_chart(kpis.spend_by(po, "WGBEZ")["spend"])

    st.subheader("Supplier ABC")
    abc = kpis.abc_suppliers(po)
    st.dataframe(abc.style.format({"spend": "€{:,.0f}", "share": "{:.1%}", "cum_share": "{:.1%}"}),
                 use_container_width=True)

    st.subheader("PO lines without a requisition")
    st.write(f"{npr['lines']} lines, €{npr['spend']:,.0f}. "
             "Not always a problem (some categories are bought without PR on purpose), "
             "but worth a look per purchasing group.")
    st.bar_chart(po[po["BANFN"] == ""].groupby("EKGRP")["NETWR"].sum())

with tab_del:
    st.subheader("Delivery performance by supplier")
    by_sup = kpis.delivery_by_supplier(dp)
    st.bar_chart(by_sup["otif"])
    st.dataframe(by_sup.style.format({"on_time": "{:.0%}", "in_full": "{:.0%}",
                                      "otif": "{:.0%}", "avg_days_late": "{:.1f}"}),
                 use_container_width=True)

    st.subheader("Late lines")
    late = dp[~dp["on_time"]].sort_values("days_late", ascending=False)
    st.dataframe(late[["EBELN", "EBELP", "NAME1", "MATNR", "EINDT", "first_gr", "days_late"]],
                 use_container_width=True, hide_index=True)

with tab_inv:
    st.subheader("Invoice vs PO price")
    over = pv[pv["over_tol"]]
    a, b, c = st.columns(3)
    a.metric("Lines over tolerance", f"{len(over)} ({pv['over_tol'].mean():.1%})")
    b.metric("Paid above PO price", f"€{pv.loc[pv['var_amt'] > 0, 'var_amt'].sum():,.0f}")
    c.metric("Lines with payment block R", f"{int(pv['blocked'].sum())}")
    st.dataframe(
        over.sort_values("var_amt", ascending=False)[
            ["EBELN", "EBELP", "NAME1", "MATNR", "po_unit", "inv_unit", "var_pct", "var_amt", "blocked"]
        ].style.format({"po_unit": "{:.3f}", "inv_unit": "{:.3f}", "var_pct": "{:.1%}", "var_amt": "€{:,.2f}"}),
        use_container_width=True, hide_index=True)

    st.subheader("GR/IR differences")
    gi = kpis.open_gr_ir(d, po)
    gi = gi[gi["gr_ir_diff"].abs() > 1]
    st.write(f"{len(gi)} PO lines where GR value and invoice value don't match "
             f"(net €{gi['gr_ir_diff'].sum():,.0f}). Includes lines not invoiced yet.")
    st.dataframe(gi[["EBELN", "EBELP", "NAME1", "gr_value", "ir_value", "gr_ir_diff"]]
                 .sort_values("gr_ir_diff", key=abs, ascending=False),
                 use_container_width=True, hide_index=True)

with tab_score:
    st.subheader("Supplier scorecard")
    w = st.slider("Weight delivery vs price", 0.0, 1.0, 0.5, 0.1)
    sc = kpis.supplier_scorecard(d, po, w_delivery=w, w_price=1 - w)
    st.dataframe(sc.style.format({"spend": "€{:,.0f}", "otif": "{:.0%}", "avg_days_late": "{:.1f}",
                                  "price_ok": "{:.0%}", "price_var_eur": "€{:,.0f}", "score": "{:.0f}"}),
                 use_container_width=True)
    st.caption("Score = weighted OTIF and share of invoice lines within price tolerance. "
               "No quality data in this sample - with QM data you'd add rejection rate.")
