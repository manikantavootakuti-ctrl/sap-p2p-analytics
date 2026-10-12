"""
P2P KPI calculations. Everything works on plain pandas DataFrames with SAP
field names, so it doesn't matter if the data comes from the generator, an
SE16N download or a CDS view extract.
"""
from pathlib import Path

import pandas as pd

DATA = Path(__file__).parent / "data"

# a GR up to this many days after the delivery date still counts as on time
ON_TIME_TOLERANCE_DAYS = 2
# invoice price more than this % above PO price counts as a variance
PRICE_VAR_TOLERANCE = 0.02


def load(folder=DATA):
    if not (folder / "ekpo_po_items.csv").exists():
        # first run - create the sample data
        import generate_data
        folder.mkdir(exist_ok=True)
        for name, df in generate_data.build().items():
            df.to_csv(folder / f"{name}.csv", index=False)

    def rd(name, dates=()):
        return pd.read_csv(folder / f"{name}.csv", dtype=str).pipe(_fix, dates)

    d = {
        "lfa1": rd("lfa1_suppliers"),
        "mara": rd("mara_materials"),
        "t023": rd("t023_material_groups"),
        "eban": rd("eban_requisitions", ["BADAT"]),
        "ekko": rd("ekko_po_header", ["BEDAT"]),
        "ekpo": rd("ekpo_po_items", ["EINDT"]),
        "mseg": rd("mseg_goods_receipts", ["BUDAT"]),
        "rseg": rd("rseg_invoices", ["BUDAT"]),
    }
    return d


def _fix(df, dates):
    for c in ("MENGE", "NETPR", "PEINH", "NETWR", "DMBTR", "WRBTR", "EBELP", "BNFPO"):
        if c in df:
            df[c] = pd.to_numeric(df[c])
    for c in dates:
        df[c] = pd.to_datetime(df[c])
    return df.fillna("")


def po_lines(d):
    """PO items joined with header, supplier and material group text."""
    po = d["ekpo"].merge(d["ekko"], on="EBELN", how="left")
    po = po.merge(d["lfa1"][["LIFNR", "NAME1", "LAND1"]], on="LIFNR", how="left")
    po = po.merge(d["t023"], on="MATKL", how="left")
    po["MONTH"] = po["BEDAT"].dt.to_period("M").dt.to_timestamp()
    return po


def filter_po(po, date_from=None, date_to=None, suppliers=None, groups=None):
    m = pd.Series(True, index=po.index)
    if date_from is not None:
        m &= po["BEDAT"] >= pd.Timestamp(date_from)
    if date_to is not None:
        m &= po["BEDAT"] <= pd.Timestamp(date_to)
    if suppliers:
        m &= po["NAME1"].isin(suppliers)
    if groups:
        m &= po["WGBEZ"].isin(groups)
    return po[m]


# ---------- spend ----------

def spend_summary(po):
    return {
        "spend": po["NETWR"].sum(),
        "po_count": po["EBELN"].nunique(),
        "po_lines": len(po),
        "suppliers": po["LIFNR"].nunique(),
        "avg_po_value": po.groupby("EBELN")["NETWR"].sum().mean() if len(po) else 0,
    }


def spend_by(po, col):
    s = po.groupby(col)["NETWR"].sum().sort_values(ascending=False)
    out = s.to_frame("spend")
    out["share"] = out["spend"] / out["spend"].sum()
    out["cum_share"] = out["share"].cumsum()
    return out


def monthly_spend(po):
    return po.groupby("MONTH")["NETWR"].sum()


def abc_suppliers(po, a=0.8, b=0.95):
    """Classic ABC on supplier spend: A = top 80%, B = next 15%, C = rest."""
    s = spend_by(po, "NAME1")
    s["class"] = "C"
    s.loc[s["cum_share"] <= b, "class"] = "B"
    s.loc[s["cum_share"] <= a, "class"] = "A"
    # first supplier is always A, even if it alone is above 80%
    if len(s):
        s.iloc[0, s.columns.get_loc("class")] = "A"
    return s


# ---------- compliance ----------

def po_without_pr(po):
    """Share of PO lines that don't reference a purchase requisition."""
    no_pr = po["BANFN"] == ""
    return {
        "lines": int(no_pr.sum()),
        "share": no_pr.mean() if len(po) else 0,
        "spend": po.loc[no_pr, "NETWR"].sum(),
    }


def pr_to_po_days(d, po):
    """Days between PR creation (EBAN-BADAT) and PO date (EKKO-BEDAT)."""
    pr = d["eban"][["BANFN", "BNFPO", "BADAT"]]
    x = po[po["BANFN"] != ""].merge(pr, on=["BANFN", "BNFPO"], how="inner")
    x["days"] = (x["BEDAT"] - x["BADAT"]).dt.days
    return x


# ---------- delivery ----------

def delivery_performance(d, po, tol=ON_TIME_TOLERANCE_DAYS):
    """
    One row per PO line that has at least one GR.
    on_time: first GR posted no later than delivery date + tolerance
    in_full: total GR qty >= PO qty
    """
    gr = d["mseg"][d["mseg"]["BWART"] == "101"]
    agg = gr.groupby(["EBELN", "EBELP"]).agg(
        first_gr=("BUDAT", "min"), gr_qty=("MENGE", "sum")).reset_index()
    x = po.merge(agg, on=["EBELN", "EBELP"], how="inner")
    x["days_late"] = (x["first_gr"] - x["EINDT"]).dt.days
    x["on_time"] = x["days_late"] <= tol
    x["in_full"] = x["gr_qty"] >= x["MENGE"]
    x["otif"] = x["on_time"] & x["in_full"]
    return x


def delivery_by_supplier(dp):
    g = dp.groupby("NAME1").agg(
        lines=("EBELN", "size"),
        on_time=("on_time", "mean"),
        in_full=("in_full", "mean"),
        otif=("otif", "mean"),
        avg_days_late=("days_late", lambda s: s.clip(lower=0).mean()),
    )
    return g.sort_values("otif")


# ---------- invoices ----------

def invoice_price_variance(d, po, tol=PRICE_VAR_TOLERANCE):
    """Compare invoice unit price with PO net price per PO line."""
    inv = d["rseg"].groupby(["EBELN", "EBELP"]).agg(
        inv_qty=("MENGE", "sum"), inv_amt=("WRBTR", "sum"),
        blocked=("ZLSPR", lambda s: (s == "R").any())).reset_index()
    x = po.merge(inv, on=["EBELN", "EBELP"], how="inner")
    x["po_unit"] = x["NETPR"] / x["PEINH"]
    x["inv_unit"] = x["inv_amt"] / x["inv_qty"]
    x["var_pct"] = x["inv_unit"] / x["po_unit"] - 1
    x["var_amt"] = (x["inv_unit"] - x["po_unit"]) * x["inv_qty"]
    x["over_tol"] = x["var_pct"] > tol
    return x


def open_gr_ir(d, po):
    """Rough GR/IR view: GR value vs invoiced value per PO line."""
    gr = d["mseg"].groupby(["EBELN", "EBELP"])["DMBTR"].sum().rename("gr_value")
    inv = d["rseg"].groupby(["EBELN", "EBELP"])["WRBTR"].sum().rename("ir_value")
    x = po.set_index(["EBELN", "EBELP"]).join(gr).join(inv).fillna({"gr_value": 0, "ir_value": 0})
    x["gr_ir_diff"] = x["gr_value"] - x["ir_value"]
    return x.reset_index()


# ---------- scorecard ----------

def supplier_scorecard(d, po, w_delivery=0.5, w_quality=0.0, w_price=0.5):
    """
    Very simple scorecard 0-100: OTIF and price compliance (share of invoice
    lines within tolerance). Quality would need QM data, so weight is 0 here.
    """
    dp = delivery_by_supplier(delivery_performance(d, po))
    pv = invoice_price_variance(d, po).groupby("NAME1").agg(
        price_ok=("over_tol", lambda s: 1 - s.mean()),
        price_var_eur=("var_amt", "sum"))
    sp = spend_by(po, "NAME1")[["spend"]]
    sc = sp.join(dp[["otif", "avg_days_late"]]).join(pv)
    sc["score"] = (100 * (w_delivery * sc["otif"].fillna(0)
                          + w_price * sc["price_ok"].fillna(0))
                   / (w_delivery + w_price + w_quality or 1)).round(0)
    return sc.sort_values("score", ascending=False)
