# Spec: TVA real fleet CSV + EIA-930 demand bootstrapping

Date: 2026-11-14
Status: agreed in interview, not yet implemented

## Goal

1. Turn `data/tva_real_plants.json` into a plants CSV that `src/check.load_plants()` reads, so the
   MILP, the cheapest-first rule and (with a coarser block) QAOA can be benchmarked on a real-scale TVA fleet.
2. Generate many realistic 24-hour demand curves from real TVA hourly load (EIA-930), by
   bootstrapping real days, plus a seeded generator for on-the-fly use.

Constraints from AGENTS.md: do not modify `src/check.py` or `reference/upstream/`; do not fill
in the team's TODOs.

## Decisions (from interview)

| Topic | Decision |
|---|---|
| Missing cost fields | Fill from **RTS-GMLC archetypes** by technology, same derivation as `data/make_data.py` |
| Nuclear, hydro, pumped storage | **Not plant rows.** Subtracted from demand (net load) |
| Multi-unit plants | **One row per plant**; archetype applied per unit: `pmin` = one unit's pmin, costs scaled to plant size |
| QUBO fit | **Configurable `BLOCK_MW`**, auto-picked for the TVA fleet; `n_slack` computed from it |
| `on_at_start` | Coal + CC = 1, CTs = 0 |
| Demand source | **EIA-930 TVA** balancing authority, bulk 6-month CSVs (no API key), cached |
| Years | **July 2018 onward** (when fuel-mix data starts) |
| Net load | Demand minus actual hourly nuclear, hydro (pumping counts as negative hydro, so it adds load back), wind, solar and other non-thermal |
| Reserve | 10% of net load (same rule as `demand.csv`) |
| Infeasible days | Days where net load + reserve > thermal capacity are **dropped**; count recorded |
| Bootstrap | **Resample whole real days** within a stratum |
| Strata | **Season (meteorological) × weekday/weekend** = 8 strata |
| Dynamic generation | Seeded generator function + saved CSV sets |
| Saved sets | **5 days per stratum** (fixed seed) + annual peak and minimum net-load days = ~42 days |
| Units in saved CSVs | **Real MW**; scaling to a smaller fleet happens at load time |
| Integration | New **`"tva"` fleet** in `FLEETS`; `load_problem("tva", day=...)` and `benchmark --fleet tva` |
| Committed to git | Processed `data/tva_hourly.csv` + generated day sets. Raw bulk files go in a gitignored cache |

## 1. Plants CSV: `data/plants_tva.csv`

Built by a new script `data/make_tva.py` (documents and rebuilds, like `make_data.py`).

Rows: every plant in the JSON with `uc_role` in `dispatchable_thermal` or `dispatchable_peaker`
(4 coal, 8 CC, 8 CT = 20 plants). Nuclear, pumped storage and hydro are excluded; their output
is handled by net load (section 2).

Columns: exactly the existing `plants.csv` columns, so `load_plants()` works unchanged:
`plant_id, type, pmin_mw, pmax_mw, marginal_cost_per_mwh, no_load_cost_per_h, startup_cost,
min_up_h, min_down_h, ramp_mw_per_h, on_at_start, rts_gen_uid, scale`.
Extra trailing columns (only if `load_plants` tolerates them; it converts every non-text column to
float, so any extra column must be numeric or added to the archetype metadata file instead):
`units`. Location, status and notes stay in the JSON.

### Archetypes

One RTS-GMLC unit per technology (choose in implementation; candidates already used in the repo):

| TVA technology | RTS-GMLC archetype |
|---|---|
| coal steam | `123_STEAM_3` (350 MW coal) |
| natural gas combined cycle | `107_CC_1` |
| combustion turbine | `113_CT_1` |

Derivation, reusing `derive()` from `make_data.py` (factor it out or import it):

- `unit_mw = capacity_mw / units` (Lagoon Creek CC with 1 unit: whole plant).
- `k_unit = unit_mw / rts_pmax`; `k_plant = capacity_mw / rts_pmax`.
- `pmin_mw = rts_pmin * k_unit` (one unit's minimum: the plant can run on a single unit).
- `pmax_mw = capacity_mw` (rounded to the fleet block only in the QUBO view, see below).
- `marginal_cost_per_mwh`, `min_up_h`, `min_down_h`: archetype values unchanged.
- `no_load_cost_per_h`, `startup_cost`, `ramp_mw_per_h`: scaled by `k_plant`.
- `scale` column = `k_plant`; `rts_gen_uid` = archetype UID.
- `on_at_start`: 1 for coal and CC, 0 for CT.

Inputs: the RTS-GMLC `gen.csv` (same URL as in `make_data.py`). Download once into the gitignored cache.

### Block size for QAOA

- New config: `BLOCK_MW` becomes per fleet, e.g. `FLEET_BLOCK_MW = {"5": 50, "10": 50, "tva": <auto>}`.
- Auto-pick: the smallest block from a candidate list (e.g. 100, 150, 200, 250, 300, 400, 500 MW)
  such that `n_plants + n_slack <= MAX_SIM_QUBITS` (default 30, the gpu-sv limit is 35).
  `n_slack = ceil(log2(sum(blocks_i) + 1))` or whatever the existing slack rule in `src/qubo.py` implies.
  Check that rule; do not change the team's TODO code.
- Every plant gets at least 1 block after rounding.
- Store the chosen block and `n_slack` in `data/tva_meta.json` so runs are reproducible.
- MILP and the rule use the unrounded `pmax_mw`; only the QUBO path uses blocks.

## 2. Demand data

### 2a. Fetch and process: `data/make_tva.py demand`

- Download the EIA-930 bulk BALANCE files `EIA930_BALANCE_<YYYY>_<Jan_Jun|Jul_Dec>.csv` for
  2018 H2 through the latest complete half-year into `data/.cache/eia930/` (gitignored).
- Filter `Balancing Authority == "TVA"`.
- Columns used: the adjusted/imputed demand, plus net generation by fuel (nuclear, hydro, wind,
  solar, other). Map EIA column names in one place.
- Times: convert UTC to local Central time (TVA dispatch day); days = local midnight to midnight.
  Drop DST transition days with 23 or 25 hours (or document another way to handle them).
- `net_load_mw = demand − nuclear − hydro − wind − solar − other`. Hydro includes pumped storage,
  so pumping hours (negative hydro) raise net load.
- Drop days with any missing hour or obvious outliers (e.g. net load ≤ 0, hourly jump > X%); log counts.
- Write `data/tva_hourly.csv`: `date, hour, demand_mw, nuclear_mw, hydro_mw, renew_other_mw,
  net_load_mw, season, daytype`. About 2,300 days × 24 rows, a few MB. Committed.

### 2b. Day pool and feasibility

- A day is feasible when `max_h(net_load + 0.10 × net_load) <= sum(pmax_mw)` of `plants_tva.csv`.
  Infeasible days are dropped from the pool; the number is recorded in `data/tva_meta.json`.
- Season: DJF winter, MAM spring, JJA summer, SON fall. Daytype: weekday / weekend
  (federal holidays count as weekend, optional).

### 2c. Generator: `src/demand.py`

```python
def tva_day_pool() -> DataFrame                          # loads data/tva_hourly.csv, feasible days only
def sample_days(season=None, daytype=None, n=1, seed=0)   # -> list[(date, demand[24], reserve[24])]
def extreme_days()                                        # annual peak and min net-load days
```

- Bootstrap = draw whole real days with replacement within the stratum, using
  `numpy.random.default_rng(seed)`. `season`/`daytype` = None means any.
- `reserve = round(0.10 × net_load)`.
- Returns real MW. Optional `scale_to=capacity_mw` rescales linearly to fit a smaller fleet.
- Same seed gives the same days.

### 2d. Saved sets: `data/demand_tva/`

- `make_tva.py sets` writes 5 days per stratum (seed fixed, e.g. 2026) plus `peak.csv` and `min.csv`:
  `data/demand_tva/<season>_<daytype>_<i>.csv`, e.g. `summer_weekday_0.csv`.
- Same format as `demand.csv` (`hour, demand_mw, reserve_mw`), where `demand_mw` = net load,
  so `load_demand()` reads them unchanged. Source date in `data/demand_tva/index.csv`
  (`file, date, season, daytype, peak_mw`).
- Committed.

## 3. Integration

- `src/config.py`:
  - `FLEETS["tva"] = ("plants_tva.csv", "demand_tva/summer_weekday_0.csv")`, the default day.
  - `load_problem(fleet, day=None)`: `day` can be a saved-set file name, or `"sample:<season>:<daytype>:<seed>"`
    for the generator.
  - Per-fleet `BLOCK_MW` and `N_SLACK` (from `tva_meta.json`).
- `experiments/benchmark.py`: add `"tva"` to `--fleet` choices and add `--day`. Optionally
  `--all-days` to loop over `data/demand_tva/index.csv` and write one summary JSON.
- `on_at_start` semantics are unchanged (the checker's rules apply).
- Update `data/README.md`: sources (TVA JSON, RTS-GMLC archetypes, EIA-930), derivation, and the
  EIA public-domain note plus RTS-GMLC credit.

## 4. Tests: `tests/test_tva.py`

All offline (no network; use committed files only).

- **Schema:** `load_plants(data/plants_tva.csv)` works; 20 rows; no NaN; `0 < pmin <= pmax`.
- **Feasibility:** every saved day and 50 generated days satisfy `max(demand + reserve) <= sum(pmax)`.
- **Determinism:** `sample_days(seed=s)` is the same for repeat calls and differs for different seeds;
  strata filters return only matching dates.
- **MILP:** `run_milp(load_problem("tva", day=...))` returns a feasible, zero-violation schedule on
  3 sample days (peak, min, one summer weekday). Mark it `@pytest.mark.slow` if it takes more than ~10 s.
- **Offline guarantee:** monkeypatch `urllib`/`requests` (socket) to raise during the test session,
  or run these tests with a fixture that blocks the network.
- **Block auto-pick:** the chosen block keeps `n_plants + n_slack <= MAX_SIM_QUBITS` and gives every plant ≥ 1 block.

## 5. Files

| File | New/changed | Committed |
|---|---|---|
| `data/make_tva.py` | new: plants + demand + sets builder | yes |
| `data/plants_tva.csv` | new | yes |
| `data/tva_hourly.csv` | new | yes |
| `data/tva_meta.json` | new: block, n_slack, dropped-day counts, source file list | yes |
| `data/demand_tva/*.csv`, `index.csv` | new | yes |
| `data/.cache/` | raw EIA and RTS files | **gitignored** |
| `src/demand.py` | new: generator | yes |
| `src/config.py` | `tva` fleet, per-fleet block, `day=` | yes |
| `experiments/benchmark.py` | `--fleet tva`, `--day` | yes |
| `tests/test_tva.py` | new | yes |
| `data/README.md` | new section | yes |

## Open items to check during implementation

- Exact EIA-930 bulk file URL pattern and column names (verify against the live EIA site).
- Whether `load_plants()` accepts extra numeric columns (it floats every non-`TEXT_COLUMNS` value).
- Whether the MILP solves 20 plants × 24 h fast enough for routine tests.
- How `src/qubo.py` sizes slack bits: the auto block size must match it without editing TODO code.
- If many summer peak days are dropped as infeasible, revisit (e.g. add an imports row) instead of silently shrinking the pool.
