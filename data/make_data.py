"""Rebuild the CSV files in this folder from the RTS-GMLC source files.

You do not need to run this. It documents exactly how the data was made.

    python make_data.py path/to/gen.csv path/to/DAY_AHEAD_regional_Load.csv

gen.csv:  https://github.com/GridMod/RTS-GMLC/blob/master/RTS_Data/SourceData/gen.csv
load:     https://github.com/GridMod/RTS-GMLC/blob/master/RTS_Data/timeseries_data_files/Load/DAY_AHEAD_regional_Load.csv
"""
import csv
import math
import sys
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent
DAY, REGION = (2020, 7, 14), 3          # a hot July weekday in RTS-GMLC region 3
LOW_MW, PEAK_MW = 280, 700              # demand range for the 5-plant fleet
RESERVE = 0.10                          # safety margin: 10% of demand

# (RTS-GMLC unit, our name, type, our pmax in MW, on at midnight?)
FIVE = [("123_STEAM_3", "COAL", "coal steam", 350, 1),
        ("107_CC_1", "GAS_CC", "gas combined cycle", 350, 0),
        ("113_CT_1", "PEAKER_A", "gas combustion turbine", 50, 0),
        ("223_CT_4", "PEAKER_B", "gas combustion turbine (older)", 50, 0),
        ("101_CT_1", "OIL", "oil combustion turbine", 50, 0)]
TEN = FIVE + [("116_STEAM_1", "COAL_MID", "coal steam (mid size)", 150, 1),
              ("201_STEAM_3", "COAL_SMALL", "coal steam (small)", 100, 0),
              ("213_CC_3", "GAS_CC_2", "gas combined cycle", 300, 0),
              ("322_CT_5", "PEAKER_C", "gas combustion turbine", 50, 0),
              ("101_CT_2", "OIL_2", "oil combustion turbine", 50, 0)]
COLUMNS = ["plant_id", "type", "pmin_mw", "pmax_mw", "marginal_cost_per_mwh", "no_load_cost_per_h",
           "startup_cost", "min_up_h", "min_down_h", "ramp_mw_per_h", "on_at_start", "rts_gen_uid", "scale"]


def derive(r, pid, label, pmax_new, on0):
    """One RTS-GMLC row -> one row of plants.csv (linear cost: no-load + marginal x MW)."""
    fuel = float(r["Fuel Price $/MMBTU"])
    pmin, pmax = float(r["PMin MW"]), float(r["PMax MW"])
    pct = [float(r[f"Output_pct_{k}"]) for k in range(4)]
    incr = [float(r[f"HR_incr_{k}"]) for k in (1, 2, 3)]            # BTU/kWh on each segment
    seg = [(pct[k + 1] - pct[k]) * pmax for k in range(3)]         # MW in each segment
    vom = float(r["VOM"]) if r["VOM"] not in ("", "NA") else 0.0
    mc = sum(s * h for s, h in zip(seg, incr)) / sum(seg) * fuel / 1000 + vom   # $/MWh
    cost_at_pmin = float(r["HR_avg_0"]) * pmin * fuel / 1000                   # $/h
    no_load = cost_at_pmin - mc * pmin
    startup = float(r["Start Heat Cold MBTU"]) * fuel + float(r["Non Fuel Start Cost $"])
    k = pmax_new / pmax                                            # size scaling
    return dict(plant_id=pid, type=label, pmin_mw=round(pmin * k), pmax_mw=pmax_new,
                marginal_cost_per_mwh=round(mc, 2), no_load_cost_per_h=round(no_load * k),
                startup_cost=int(round(startup * k, -1)),
                min_up_h=math.ceil(float(r["Min Up Time Hr"])),
                min_down_h=math.ceil(float(r["Min Down Time Hr"])),
                ramp_mw_per_h=round(float(r["Ramp Rate MW/Min"]) * 60 * k),
                on_at_start=on0, rts_gen_uid=r["GEN UID"], scale=round(k, 3))


def main(gen_path, load_path):
    with open(gen_path) as f:
        gen = {r["GEN UID"]: r for r in csv.DictReader(f)}
    for name, fleet in (("plants.csv", FIVE), ("plants10.csv", TEN)):
        with open(OUT / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            for uid, pid, label, pmax_new, on0 in fleet:
                w.writerow(derive(gen[uid], pid, label, pmax_new, on0))

    with open(load_path) as f:
        rows = list(csv.reader(f))[1:]
    shape = np.array([float(r[3 + REGION]) for r in rows
                      if (int(r[0]), int(r[1]), int(r[2])) == DAY])
    demand = np.round(LOW_MW + (PEAK_MW - LOW_MW) * (shape - shape.min()) / (shape.max() - shape.min()))
    cap5 = sum(x[3] for x in FIVE)
    cap10 = sum(x[3] for x in TEN)
    for name, factor in (("demand.csv", 1.0), ("demand10.csv", cap10 / cap5)):
        with open(OUT / name, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["hour", "demand_mw", "reserve_mw"])
            for t, d in enumerate(demand):
                d = round(d * factor)
                w.writerow([t, d, round(RESERVE * d)])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
