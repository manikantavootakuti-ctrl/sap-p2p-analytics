"""
Static version of the dashboard - prints the main KPIs and saves the charts
as PNGs into ./images (that's where the screenshots in the README come from).

    python report.py
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick

import kpis

IMG = Path(__file__).parent / "images"
BLUE, GREY, RED = "#2f6db5", "#9aa5b1", "#c8553d"

plt.rcParams.update({
    "figure.dpi": 110, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.alpha": 0.25, "font.size": 10,
})


def eur(x, _=None):
    return f"€{x/1000:,.0f}k"


def main():
    IMG.mkdir(exist_ok=True)
    d = kpis.load()
    po = kpis.po_lines(d)

    s = kpis.spend_summary(po)
    npr = kpis.po_without_pr(po)
    lead = kpis.pr_to_po_days(d, po)["days"]
    dp = kpis.delivery_performance(d, po)
    pv = kpis.invoice_price_variance(d, po)

    print(f"Spend:              €{s['spend']:,.0f}")
    print(f"POs / lines:        {s['po_count']} / {s['po_lines']}")
    print(f"Avg PO value:       €{s['avg_po_value']:,.0f}")
    print(f"PO lines w/o PR:    {npr['share']:.1%}  (€{npr['spend']:,.0f})")
    print(f"PR -> PO (median):  {lead.median():.0f} days")
    print(f"OTIF:               {dp['otif'].mean():.1%}")
    print(f"Invoice lines > {kpis.PRICE_VAR_TOLERANCE:.0%} over PO price: "
          f"{pv['over_tol'].mean():.1%}  (€{pv.loc[pv['var_amt'] > 0, 'var_amt'].sum():,.0f} paid above PO)")

    # monthly spend
    m = kpis.monthly_spend(po)
    fig, ax = plt.subplots(figsize=(8, 3.2))
    ax.bar(m.index, m.values, width=20, color=BLUE)
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(eur))
    ax.set_title("Monthly PO spend", loc="left", fontweight="bold")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(IMG / "monthly_spend.png")

    # spend by material group
    g = kpis.spend_by(po, "WGBEZ")["spend"].sort_values()
    fig, ax = plt.subplots(figsize=(6, 3.2))
    ax.barh(g.index, g.values, color=BLUE)
    ax.xaxis.set_major_formatter(mtick.FuncFormatter(eur))
    ax.set_title("Spend by material group", loc="left", fontweight="bold")
    fig.tight_layout()
    fig.savefig(IMG / "spend_by_group.png")

    # OTIF by supplier
    sup = kpis.delivery_by_supplier(dp)
    fig, ax = plt.subplots(figsize=(6, 3.4))
    colors = [RED if v < 0.8 else BLUE for v in sup["otif"]]
    ax.barh(sup.index, sup["otif"], color=colors)
    ax.axvline(0.9, color=GREY, ls="--", lw=1)
    ax.text(0.9, len(sup) - 0.45, " target 90%", color=GREY, fontsize=8, va="bottom")
    ax.xaxis.set_major_formatter(mtick.PercentFormatter(1.0))
    ax.set_xlim(0, 1)
    ax.set_title("OTIF by supplier", loc="left", fontweight="bold")
    fig.tight_layout()
    fig.savefig(IMG / "otif_by_supplier.png")

    # invoice price variance distribution
    fig, ax = plt.subplots(figsize=(6, 3.2))
    ax.hist(pv["var_pct"].clip(-0.1, 0.15), bins=40, color=BLUE)
    ax.axvline(kpis.PRICE_VAR_TOLERANCE, color=RED, ls="--", lw=1)
    ax.xaxis.set_major_formatter(mtick.PercentFormatter(1.0))
    ax.set_yscale("log")
    ax.set_title("Invoice vs PO price (per line)", loc="left", fontweight="bold")
    ax.set_xlabel("difference to PO price")
    fig.tight_layout()
    fig.savefig(IMG / "price_variance.png")

    print("\nSupplier scorecard")
    sc = kpis.supplier_scorecard(d, po)
    print(sc[["spend", "otif", "price_ok", "score"]].to_string(
        formatters={"spend": "€{:,.0f}".format, "otif": "{:.0%}".format,
                    "price_ok": "{:.0%}".format, "score": "{:.0f}".format}))
    print(f"\ncharts saved to {IMG}/")


if __name__ == "__main__":
    main()
