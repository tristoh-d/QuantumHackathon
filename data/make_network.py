"""Rebuild network_rts3.csv (the 3-area grid used by the QPE / HHL approach) from RTS-GMLC.

    python data/make_network.py path/to/branch.csv

branch.csv: https://github.com/GridMod/RTS-GMLC/blob/master/RTS_Data/SourceData/branch.csv

RTS-GMLC has three areas (bus numbers 1xx, 2xx, 3xx). We keep one node per area and one
equivalent line per pair of areas. Parallel tie lines add their susceptances (1 / X, per unit
on a 100 MVA base) and their continuous ratings (MW). Lines inside an area are dropped.
"""
import csv
import sys
from pathlib import Path

AREAS = {"1": "A", "2": "B", "3": "C"}
COST_PER_MWH = 2.0          # our assumption: RTS-GMLC has no transmission prices (see data/README.md)
OUT = Path(__file__).with_name("network_rts3.csv")


def main(branch_csv):
    ties = {}
    with open(branch_csv, newline="") as f:
        for r in csv.DictReader(f):
            a, b = sorted((AREAS[r["From Bus"][0]], AREAS[r["To Bus"][0]]))
            if a == b:
                continue
            t = ties.setdefault((a, b), dict(lines=[], b_pu=0.0, rating_mw=0.0))
            t["lines"].append(r["UID"])
            t["b_pu"] += 1 / float(r["X"])
            t["rating_mw"] += float(r["Cont Rating"])
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["from_area", "to_area", "rts_lines", "susceptance_pu", "rating_mw", "cost_per_mwh"])
        for (a, b), t in sorted(ties.items()):
            w.writerow([a, b, " ".join(t["lines"]), round(t["b_pu"], 4), round(t["rating_mw"]), COST_PER_MWH])
    print(f"wrote {OUT.name}: {len(ties)} area-to-area lines")


if __name__ == "__main__":
    main(sys.argv[1])
