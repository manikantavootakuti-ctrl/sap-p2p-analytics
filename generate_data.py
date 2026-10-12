"""
Generates a fake but realistic-looking P2P dataset, shaped like the SAP tables
I'd normally pull (EBAN, EKKO, EKPO, EKET, MSEG/MATDOC, RBKP/RSEG, LFA1, MARA).

Column names follow the SAP field names so the same scripts work on a real
extract with only small changes.

    python generate_data.py            -> writes CSVs into ./data
    python generate_data.py --seed 7   -> different random data
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).parent / "data"

SUPPLIERS = [
    # LIFNR, NAME1, LAND1, reliability (0-1), price drift
    ("100001", "Example Steel GmbH", "DE", 0.92, 0.01),
    ("100002", "Sample Fasteners AG", "DE", 0.97, 0.00),
    ("100003", "Demo Packaging BV", "NL", 0.85, 0.02),
    ("100004", "Test Bearings SRL", "IT", 0.70, 0.04),
    ("100005", "Muster Elektro GmbH", "DE", 0.90, 0.01),
    ("100006", "Probe Chemicals SA", "FR", 0.80, 0.03),
    ("100007", "Mock Plastics Sp. z o.o.", "PL", 0.88, 0.02),
    ("100008", "Fake Logistics Kft", "HU", 0.75, 0.05),
]

MATERIAL_GROUPS = {
    "M001": "Metals",
    "M002": "Fasteners",
    "M003": "Electrical",
    "M004": "Chemicals",
    "M005": "Packaging",
    "M006": "Plastics",
    "M007": "Spare parts",
}

# MATNR, MAKTX, MATKL, base price EUR, main supplier
MATERIALS = [
    ("RM-100", "Steel sheet 2mm", "M001", 10.00, "100001"),
    ("RM-101", "Aluminium bar 20mm", "M001", 6.40, "100001"),
    ("RM-102", "Copper wire 1.5mm", "M001", 8.90, "100005"),
    ("RM-205", "Hex bolt M8x40", "M002", 0.12, "100002"),
    ("RM-206", "Washer M8", "M002", 0.03, "100002"),
    ("RM-207", "Nut M8", "M002", 0.05, "100002"),
    ("EL-400", "Relay 24V", "M003", 3.20, "100005"),
    ("EL-401", "Cable gland M20", "M003", 1.10, "100005"),
    ("CH-500", "Degreaser 5L", "M004", 18.50, "100006"),
    ("CH-501", "Paint primer 10L", "M004", 42.00, "100006"),
    ("PK-010", "Carton box 40x30x20", "M005", 0.85, "100003"),
    ("PK-011", "Stretch film 500mm", "M005", 12.00, "100003"),
    ("PL-600", "PP granulate 25kg", "M006", 38.00, "100007"),
    ("PL-601", "ABS sheet 3mm", "M006", 15.50, "100007"),
    ("SP-300", "Bearing 6204", "M007", 4.90, "100004"),
    ("SP-301", "V-belt A42", "M007", 7.80, "100004"),
    ("SP-302", "Hydraulic hose 1m", "M007", 22.00, "100008"),
]

PURCH_GROUPS = ["001", "002", "003"]
PLANTS = ["1100", "1200"]


def build(seed: int = 42, n_po: int = 500, start="2025-01-01", end="2026-09-30"):
    rng = np.random.default_rng(seed)
    days = pd.date_range(start, end, freq="D")
    days = days[days.weekday < 5]  # buyers don't work weekends (mostly)

    sup = pd.DataFrame(SUPPLIERS, columns=["LIFNR", "NAME1", "LAND1", "_rel", "_drift"])
    mat = pd.DataFrame(MATERIALS, columns=["MATNR", "MAKTX", "MATKL", "_price", "_lifnr"])

    pr_rows, ekko_rows, ekpo_rows, gr_rows, inv_rows = [], [], [], [], []
    banfn, ebeln, mblnr, belnr = 10000000, 4500000000, 5000000000, 5100000000

    for _ in range(n_po):
        ebeln += 1
        bedat = rng.choice(days)
        bedat = pd.Timestamp(bedat)

        # most of the time the usual supplier, sometimes someone else
        first = mat.sample(1, random_state=int(rng.integers(1e9))).iloc[0]
        lifnr = first["_lifnr"] if rng.random() < 0.85 else rng.choice(sup["LIFNR"])
        s = sup.set_index("LIFNR").loc[lifnr]

        ekko_rows.append({
            "EBELN": str(ebeln), "BSART": "NB", "LIFNR": lifnr, "EKORG": "1000",
            "EKGRP": rng.choice(PURCH_GROUPS), "BEDAT": bedat.date(), "WAERS": "EUR",
        })

        # 1-4 items, mostly from the same material group as the first one
        n_items = int(rng.choice([1, 1, 2, 2, 3, 4]))
        same_grp = mat[mat["MATKL"] == first["MATKL"]]
        items = same_grp.sample(min(n_items, len(same_grp)),
                                random_state=int(rng.integers(1e9)))

        has_pr = rng.random() < 0.8  # ~20% POs without a PR
        for pos, (_, m) in enumerate(items.iterrows(), start=1):
            ebelp = pos * 10
            months_in = (bedat.year - 2025) * 12 + bedat.month
            price = m["_price"] * (1 + s["_drift"]) ** (months_in / 12)
            price *= rng.normal(1, 0.03)
            peinh = 100 if m["_price"] < 0.5 else 1
            netpr = round(price * peinh, 2)
            qty = int(rng.choice([50, 100, 200, 250, 500, 1000, 2000])
                      if m["_price"] < 5 else rng.choice([5, 10, 20, 25, 50, 100]))
            werks = rng.choice(PLANTS)
            lead = int(rng.integers(5, 25))
            eindt = bedat + pd.Timedelta(days=lead)

            b_no, b_pos = "", ""
            if has_pr:
                if pos == 1:
                    banfn += 1
                badat = bedat - pd.Timedelta(days=int(rng.gamma(2.0, 2.5)))
                b_no, b_pos = str(banfn), ebelp
                pr_rows.append({
                    "BANFN": b_no, "BNFPO": b_pos, "MATNR": m["MATNR"], "MENGE": qty,
                    "WERKS": werks, "BADAT": badat.date(), "EBELN": str(ebeln),
                })

            ekpo_rows.append({
                "EBELN": str(ebeln), "EBELP": ebelp, "MATNR": m["MATNR"],
                "MATKL": m["MATKL"], "WERKS": werks, "MENGE": qty,
                "MEINS": "PC", "NETPR": netpr, "PEINH": peinh,
                "NETWR": round(qty * netpr / peinh, 2), "EINDT": eindt.date(),
                "BANFN": b_no, "BNFPO": b_pos,
            })

            # goods receipts - skip if delivery date is in the future
            if eindt > pd.Timestamp(end):
                continue
            late = 0 if rng.random() < s["_rel"] else int(rng.integers(1, 15))
            early = int(rng.integers(0, 3)) if late == 0 else 0
            gr_date = eindt + pd.Timedelta(days=late - early)
            split = rng.random() < 0.12
            gr_qty = [qty] if not split else [round(qty * 0.6), qty - round(qty * 0.6)]
            if rng.random() < 0.04:  # small under-delivery that never got closed
                gr_qty[-1] = int(gr_qty[-1] * 0.9)
            for k, q in enumerate(gr_qty):
                mblnr += 1
                gr_rows.append({
                    "MBLNR": str(mblnr), "MJAHR": (gr_date + pd.Timedelta(days=7 * k)).year,
                    "BWART": "101", "EBELN": str(ebeln), "EBELP": ebelp,
                    "MATNR": m["MATNR"], "MENGE": q,
                    "BUDAT": (gr_date + pd.Timedelta(days=7 * k)).date(),
                    "DMBTR": round(q * netpr / peinh, 2),
                })

            # invoice - most match, some with price differences
            last_gr = gr_date + pd.Timedelta(days=7 * (len(gr_qty) - 1))
            inv_date = last_gr + pd.Timedelta(days=int(rng.integers(2, 20)))
            if inv_date > pd.Timestamp(end):
                continue
            inv_qty = sum(gr_qty)
            inv_price = netpr
            r = rng.random()
            if r < 0.10:
                inv_price = round(netpr * rng.uniform(1.02, 1.12), 2)
            elif r < 0.13:
                inv_price = round(netpr * rng.uniform(0.95, 0.99), 2)
            belnr += 1
            blocked = "R" if inv_price > netpr * 1.05 else ""
            inv_rows.append({
                "BELNR": str(belnr), "GJAHR": inv_date.year, "EBELN": str(ebeln),
                "EBELP": ebelp, "LIFNR": lifnr, "BUDAT": inv_date.date(),
                "MENGE": inv_qty, "WRBTR": round(inv_qty * inv_price / peinh, 2),
                "ZLSPR": blocked,
            })

    out = {
        "lfa1_suppliers": sup.drop(columns=["_rel", "_drift"]),
        "mara_materials": mat.drop(columns=["_price", "_lifnr"]),
        "t023_material_groups": pd.DataFrame(
            list(MATERIAL_GROUPS.items()), columns=["MATKL", "WGBEZ"]),
        "eban_requisitions": pd.DataFrame(pr_rows),
        "ekko_po_header": pd.DataFrame(ekko_rows),
        "ekpo_po_items": pd.DataFrame(ekpo_rows),
        "mseg_goods_receipts": pd.DataFrame(gr_rows),
        "rseg_invoices": pd.DataFrame(inv_rows),
    }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--pos", type=int, default=500, help="number of POs")
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    for name, df in build(args.seed, args.pos).items():
        df.to_csv(OUT / f"{name}.csv", index=False)
        print(f"{name:25s} {len(df):6d} rows")


if __name__ == "__main__":
    main()
