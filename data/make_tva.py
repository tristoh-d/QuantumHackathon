"""Build the TVA fleet and the TVA demand data from public sources.

You do not need to run this: its outputs are committed. It documents exactly how they were made.

    python data/make_tva.py fetch     # download RTS-GMLC gen.csv + TVA rows of the EIA-930 bulk files
    python data/make_tva.py plants    # tva_real_plants.json + RTS-GMLC archetypes -> plants_tva.csv
    python data/make_tva.py demand    # EIA-930 TVA rows -> tva_hourly.csv (net load per hour)
    python data/make_tva.py sets      # bootstrap saved demand days -> demand_tva/*.csv
    python data/make_tva.py all       # all four, in order

Downloads go to data/.cache/ (gitignored). Each EIA-930 bulk file (about 40 MB, every balancing
authority) is streamed and only its TVA rows are kept, so the cache stays a few MB.

Sources:
  RTS-GMLC gen.csv  https://github.com/GridMod/RTS-GMLC/blob/master/RTS_Data/SourceData/gen.csv
  EIA-930 bulk      https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_<YYYY>_<Jan_Jun|Jul_Dec>.csv
"""
import csv
import datetime as dt
import io
import json
import math
import sys
import urllib.request
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))           # so `src` imports work when run as a script
sys.path.insert(0, str(HERE))           # make_data.derive

from make_data import COLUMNS, derive  # noqa: E402

CACHE = HERE / ".cache"
GEN_URL = "https://raw.githubusercontent.com/GridMod/RTS-GMLC/master/RTS_Data/SourceData/gen.csv"
EIA_URL = "https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_{year}_{half}.csv"
FIRST_HALF = (2018, "Jul_Dec")          # fuel-mix data starts July 2018
BA = "TVA"

# ---------------------------------------------------------------- plants
# Archetype per TVA plant (RTS-GMLC GEN UID).
# Coal: the RTS unit whose size is closest to one TVA unit (350 MW or 155 MW class).
# CC and CT: TVA plants sorted by commissioning year, newest gets the cheapest archetype
# (lowest marginal cost). Not used: RTS units with a negative derived no-load cost, and 218_CC_1
# (its no-load cost, 3,400 $/h per 355 MW, is about 10x the other CC units).
COAL_ARCHETYPES = {350: ["123_STEAM_3", "223_STEAM_3"], 155: ["116_STEAM_1", "216_STEAM_1", "115_STEAM_3"]}
CC_ARCHETYPES = ["313_CC_1", "107_CC_1", "321_CC_1", "118_CC_1", "318_CC_1", "213_CC_3"]
CT_ARCHETYPES = ["322_CT_5", "315_CT_6", "215_CT_4", "113_CT_1", "123_CT_1", "307_CT_1", "301_CT_3", "223_CT_4"]
THERMAL_ROLES = ("dispatchable_thermal", "dispatchable_peaker")
ON_AT_START = {"coal": 1, "cc": 1, "ct": 0}

# QAOA block size: the smallest candidate that keeps plants + slack bits under the limit.
BLOCK_CANDIDATES = (100, 150, 200, 250, 300, 400, 500)
MAX_SIM_QUBITS = 30

# ---------------------------------------------------------------- demand
RESERVE = 0.10
G = "Net Generation (MW) from "
# our name -> EIA-930 columns, summed. Each value is the "(Adjusted)" column when present, else the raw one.
# From July 2024 EIA splits hydro into conventional + pumped storage, and solar/wind/storage into
# several columns; listing both the old and new names covers every file (absent columns are skipped).
EIA_COLS = {
    "demand_mw": ["Demand (MW)"],
    "nuclear_mw": [G + "Nuclear"],
    "hydro_mw": [G + "Hydropower and Pumped Storage",
                 G + "Hydropower Excluding Pumped Storage", G + "Pumped Storage"],
    "renew_other_mw": [G + "Solar", G + "Solar without Integrated Battery Storage",
                       G + "Solar with Integrated Battery Storage", G + "Wind",
                       G + "Wind without Integrated Battery Storage", G + "Wind with Integrated Battery Storage",
                       G + "Battery Storage", G + "Other Energy Storage", G + "Unknown Energy Storage",
                       G + "Geothermal", G + "Other Fuel Sources"],
}
MAX_JUMP = 0.30         # drop a day if net load changes by more than 30% of its daily max in one hour
SEASONS = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
           6: "summer", 7: "summer", 8: "summer", 9: "fall", 10: "fall", 11: "fall"}
HOURLY_COLUMNS = ["date", "hour", "demand_mw", "nuclear_mw", "hydro_mw", "renew_other_mw", "net_load_mw",
                  "season", "daytype"]

SETS_SEED = 2026
SETS_PER_STRATUM = 5


def tech(plant):
    t = plant["technology"]
    return "coal" if plant["fuel"] == "coal" else "cc" if "combined" in t else "ct"


# ================================================================ fetch
def halves(today=None):
    """(year, half) for every complete 6-month EIA-930 file from July 2018 on."""
    today = today or dt.date.today()
    year, half = FIRST_HALF
    out = []
    while True:
        end = dt.date(year, 6, 30) if half == "Jan_Jun" else dt.date(year, 12, 31)
        if end >= today:
            break
        out.append((year, half))
        year, half = (year, "Jul_Dec") if half == "Jan_Jun" else (year + 1, "Jan_Jun")
    return out


def fetch():
    CACHE.mkdir(exist_ok=True)
    (CACHE / ".gitignore").write_text("*\n")
    gen = CACHE / "rts_gen.csv"
    if not gen.exists():
        print("RTS-GMLC gen.csv")
        urllib.request.urlretrieve(GEN_URL, gen)
    eia_dir = CACHE / "eia930"
    eia_dir.mkdir(exist_ok=True)
    for year, half in halves():
        out = eia_dir / f"{BA}_{year}_{half}.csv"
        if out.exists():
            continue
        url = EIA_URL.format(year=year, half=half)
        print(f"EIA-930 {year} {half} ... ", end="", flush=True)
        kept = 0
        with urllib.request.urlopen(url, timeout=300) as resp, open(out.with_suffix(".part"), "w", newline="") as f:
            lines = io.TextIOWrapper(resp, encoding="utf-8-sig", newline="")
            header = next(lines)
            f.write(header)
            for line in lines:
                if line.startswith(BA + ",") or line.startswith(f'"{BA}",'):
                    f.write(line)
                    kept += 1
        out.with_suffix(".part").replace(out)
        print(f"{kept} TVA rows")


# ================================================================ plants
def build_plants():
    fleet = json.loads((HERE / "tva_real_plants.json").read_text())["plants"]
    with open(CACHE / "rts_gen.csv") as f:
        gen = {r["GEN UID"]: r for r in csv.DictReader(f)}
    thermal = [p for p in fleet if p["uc_role"] in THERMAL_ROLES]

    archetype = {}
    coal_used = {350: 0, 155: 0}
    for p in thermal:
        if tech(p) == "coal":
            unit = p["capacity_mw"] / p["units"]
            size = min(COAL_ARCHETYPES, key=lambda s: abs(s - unit))
            archetype[p["plant_id"]] = COAL_ARCHETYPES[size][coal_used[size] % len(COAL_ARCHETYPES[size])]
            coal_used[size] += 1
    for kind, pool in (("cc", CC_ARCHETYPES), ("ct", CT_ARCHETYPES)):
        group = sorted((p for p in thermal if tech(p) == kind), key=lambda p: -p["commissioned"])
        for k, p in enumerate(group):          # newest first -> cheapest archetype
            archetype[p["plant_id"]] = pool[k % len(pool)]

    rows = []
    for p in thermal:
        r = gen[archetype[p["plant_id"]]]
        rts_pmax = float(r["PMax MW"])
        units = p["units"] or 1
        unit_mw = p["capacity_mw"] / units
        k_plant = p["capacity_mw"] / rts_pmax
        k_unit = unit_mw / rts_pmax
        d = derive(r, p["plant_id"], f"{p['fuel']} {p['technology']}", p["capacity_mw"], ON_AT_START[tech(p)])
        # derive() scales everything by k_plant; pmin is one unit's minimum instead.
        d["pmin_mw"] = round(float(r["PMin MW"]) * k_unit)
        assert math.isclose(d["scale"], round(k_plant, 3))
        assert d["no_load_cost_per_h"] >= 0, p["plant_id"]
        rows.append(d)

    with open(HERE / "plants_tva.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    block, n_slack, n_qubits = pick_block([r["pmax_mw"] for r in rows])
    update_meta(plants=dict(n_plants=len(rows), capacity_mw=sum(r["pmax_mw"] for r in rows),
                            archetypes=archetype, block_mw=block, n_slack=n_slack, n_qubits=n_qubits,
                            max_sim_qubits=MAX_SIM_QUBITS))
    print(f"plants_tva.csv: {len(rows)} plants, {sum(r['pmax_mw'] for r in rows)} MW; "
          f"QAOA block {block} MW, {n_slack} slack bits, {n_qubits} qubits")


def pick_block(pmax_list, candidates=BLOCK_CANDIDATES, max_qubits=MAX_SIM_QUBITS):
    """Smallest block (MW) with n_plants + n_slack <= max_qubits; see src/demand.block_layout."""
    from src.demand import block_layout
    for block in candidates:
        blocks, n_slack = block_layout(pmax_list, block)
        if len(blocks) + n_slack <= max_qubits:
            return block, n_slack, len(blocks) + n_slack
    raise ValueError(f"no block size in {candidates} fits {max_qubits} qubits")


# ================================================================ demand
def _value(row, cols):
    """Sum of the listed columns that have a value (Adjusted preferred); None if none has one."""
    vals = []
    for col in cols:
        for name in (f"{col} (Adjusted)", col):
            v = row.get(name) or ""
            if v.strip():
                vals.append(float(v.replace(",", "")))
                break
    return sum(vals) if vals else None


def build_demand():
    days = {}                                  # date -> {hour: values}
    for path in sorted((CACHE / "eia930").glob(f"{BA}_*.csv")):
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                date = dt.datetime.strptime(row["Data Date"], "%m/%d/%Y").date()
                vals = {k: _value(row, c) for k, c in EIA_COLS.items()}
                days.setdefault(date, {})[int(row["Hour Number"])] = vals

    dropped = dict(not_24_hours=0, missing_value=0, nonpositive=0, jump=0)
    out = []
    for date in sorted(days):
        hrs = days[date]
        if sorted(hrs) != list(range(1, 25)):          # DST days (23/25 h) and gaps
            dropped["not_24_hours"] += 1
            continue
        rows = [hrs[h] for h in range(1, 25)]
        if any(r["demand_mw"] is None or r["nuclear_mw"] is None or r["hydro_mw"] is None for r in rows):
            dropped["missing_value"] += 1
            continue
        net = np.array([r["demand_mw"] - r["nuclear_mw"] - r["hydro_mw"] - (r["renew_other_mw"] or 0.0)
                        for r in rows])
        if net.min() <= 0:
            dropped["nonpositive"] += 1
            continue
        if np.abs(np.diff(net)).max() > MAX_JUMP * net.max():
            dropped["jump"] += 1
            continue
        season = SEASONS[date.month]
        daytype = "weekend" if date.weekday() >= 5 else "weekday"
        for h, (r, n) in enumerate(zip(rows, net)):
            out.append([date.isoformat(), h, round(r["demand_mw"]), round(r["nuclear_mw"]), round(r["hydro_mw"]),
                        round(r["renew_other_mw"] or 0.0), round(n), season, daytype])

    with open(HERE / "tva_hourly.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HOURLY_COLUMNS)
        w.writerows(out)
    n_days = len(out) // 24
    first, last = out[0][0], out[-1][0]
    update_meta(demand=dict(source="EIA-930 bulk BALANCE files, balancing authority TVA",
                            first_day=first, last_day=last, days_raw=len(days), days_kept=n_days,
                            dropped=dropped, reserve_share=RESERVE, max_jump_share=MAX_JUMP))
    print(f"tva_hourly.csv: {n_days} days {first} .. {last}; dropped {dropped}")


# ================================================================ saved sets
def build_sets():
    from src.demand import SEASON_ORDER, DAYTYPES, extreme_days, pool_stats, sample_days, write_demand_csv
    out = HERE / "demand_tva"
    out.mkdir(exist_ok=True)
    for old in out.glob("*.csv"):
        old.unlink()
    index = []
    for season in SEASON_ORDER:
        for daytype in DAYTYPES:
            seed = SETS_SEED + 10 * SEASON_ORDER.index(season) + DAYTYPES.index(daytype)
            for i, day in enumerate(sample_days(season, daytype, n=SETS_PER_STRATUM, seed=seed, replace=False)):
                name = f"{season}_{daytype}_{i}"
                write_demand_csv(out / f"{name}.csv", day)
                index.append([name, day.date, season, daytype, int(day.demand.max()), int(day.demand.min())])
    for kind, day in extreme_days().items():
        write_demand_csv(out / f"{kind}.csv", day)
        index.append([kind, day.date, day.season, day.daytype, int(day.demand.max()), int(day.demand.min())])
    with open(out / "index.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "date", "season", "daytype", "peak_mw", "min_mw"])
        w.writerows(index)
    update_meta(pool=pool_stats(), sets=dict(seed=SETS_SEED, per_stratum=SETS_PER_STRATUM, files=len(index)))
    print(f"demand_tva/: {len(index)} days; pool {pool_stats()}")


# ================================================================ meta
def update_meta(**sections):
    path = HERE / "tva_meta.json"
    meta = json.loads(path.read_text()) if path.exists() else {}
    meta.update(sections)
    path.write_text(json.dumps(meta, indent=1, default=str) + "\n")


STEPS = {"fetch": fetch, "plants": build_plants, "demand": build_demand, "sets": build_sets}

if __name__ == "__main__":
    steps = sys.argv[1:] or ["all"]
    for s in (list(STEPS) if steps == ["all"] else steps):
        STEPS[s]()
