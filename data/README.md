# Data

All plants and the demand curve come from **RTS-GMLC**, an open test power system published by NREL and partners: https://github.com/GridMod/RTS-GMLC

Files used:
- `RTS_Data/SourceData/gen.csv` (one row per generating unit)
- `RTS_Data/timeseries_data_files/Load/DAY_AHEAD_regional_Load.csv` (hourly load for 2020, three regions)

`make_data.py` rebuilds every CSV here from those two files. You do not need to run it.

## Files

| File | Rows | What it is |
|---|---|---|
| `plants.csv` | 5 | The main fleet: COAL, GAS_CC, PEAKER_A, PEAKER_B, OIL |
| `demand.csv` | 24 | `demand_mw` and `reserve_mw` for hours 0 to 23 |
| `plants10.csv` | 10 | Stretch fleet: the same 5 plants plus COAL_MID, COAL_SMALL, GAS_CC_2, PEAKER_C, OIL_2 |
| `demand10.csv` | 24 | The same demand curve, scaled to the 10-plant fleet |

## Plant columns

| Column | Meaning | How it was made from `gen.csv` |
|---|---|---|
| `plant_id`, `type` | Our short name and a plain description | |
| `rts_gen_uid` | The RTS-GMLC unit it came from | `GEN UID` |
| `pmin_mw`, `pmax_mw` | Output range when on | `PMin MW`, `PMax MW`, then scaled (below) |
| `marginal_cost_per_mwh` | Dollars per extra MWh | Average of the three incremental heat-rate segments (`HR_incr_1..3`, weighted by segment size) × `Fuel Price $/MMBTU` / 1000, plus `VOM` (0 for these units) |
| `no_load_cost_per_h` | Dollars per hour of just being on | Cost at pmin (`HR_avg_0` × pmin × fuel price / 1000) minus marginal cost × pmin. Together these give a straight-line cost: no-load + marginal × MW |
| `startup_cost` | Dollars per start | `Start Heat Cold MBTU` × fuel price + `Non Fuel Start Cost $` (cold start, to keep one number per plant) |
| `min_up_h`, `min_down_h` | Hours a plant must stay on / off after switching | `Min Up Time Hr`, `Min Down Time Hr`, rounded up to whole hours |
| `ramp_mw_per_h` | Largest output change in one hour | `Ramp Rate MW/Min` × 60 (used only in the ramp stretch goal) |
| `on_at_start` | 1 if running at midnight | Our choice: COAL (and COAL_MID in the 10-plant set). Every plant is assumed to have been in its midnight state long enough to switch freely. |
| `scale` | Size factor applied to the unit | See below |

## Scaling

Each plant's `pmax_mw` was rounded to a multiple of 50 MW so the safety-margin rule can be counted in 50 MW blocks (this is what lets 3 helper qubits encode it exactly). The size factor `scale` = new pmax / RTS pmax was also applied to pmin, no-load cost, startup cost and ramp rate. Marginal cost and min up/down times are unchanged, so each plant keeps its real character.

| Plant | RTS unit | RTS pmax | Our pmax | scale |
|---|---|---|---|---|
| COAL | 123_STEAM_3 | 350 | 350 | 1.0 |
| GAS_CC | 107_CC_1 | 355 | 350 | 0.986 |
| PEAKER_A | 113_CT_1 | 55 | 50 | 0.909 |
| PEAKER_B | 223_CT_4 | 55 | 50 | 0.909 |
| OIL | 101_CT_1 | 20 | 50 | 2.5 |
| COAL_MID | 116_STEAM_1 | 155 | 150 | 0.968 |
| COAL_SMALL | 201_STEAM_3 | 76 | 100 | 1.316 |
| GAS_CC_2 | 213_CC_3 | 355 | 300 | 0.845 |
| PEAKER_C | 322_CT_5 | 55 | 50 | 0.909 |
| OIL_2 | 101_CT_2 | 20 | 50 | 2.5 |

OIL has the biggest change (20 MW to 50 MW) so that it counts as one full block. COAL_SMALL was rounded up to two blocks (100 MW). GAS_CC_2 was made smaller (300 MW) so it is not an exact twin of GAS_CC.

## Demand

- Source day: the RTS-GMLC day-ahead load for **region 3 on July 14, 2020** (a hot weekday). RTS periods 1 to 24 are our hours 0 to 23.
- We kept the shape of that day and rescaled it linearly so the lowest hour is 280 MW and the highest is 700 MW. (The real day's low is 46% of its peak; stretching it to 40% lets the gas plant switch off overnight, which makes the puzzle more interesting.)
- `reserve_mw` = 10% of demand, rounded to the nearest MW.
- `demand10.csv` is the same curve times 1500/850 (the 10-plant fleet's capacity over the 5-plant fleet's), with its own 10% reserve.

## Grid (QPE / HHL approach)

`network_rts3.csv` is the grid used by the QPE / HHL approach (`src/network.py`, `docs/qpe_results.md`). It is built from RTS-GMLC `RTS_Data/SourceData/branch.csv` by `make_network.py`:

- One node per RTS-GMLC area: A (buses 1xx), B (2xx), C (3xx). Each plant sits in the area of its RTS bus (`rts_gen_uid`). The whole demand is in area C, because the demand curve is region 3 load.
- One equivalent line per pair of areas. Parallel tie lines add their susceptances (1 / `X`, per unit on 100 MVA) and their `Cont Rating`. Lines inside an area are dropped.

| Line | RTS tie lines | Susceptance (pu) | Rating (MW) |
|---|---|---|---|
| A-B | AB1, AB2, AB3 | 33.058 | 1,175 |
| A-C | CA-1 | 10.309 | 500 |
| B-C | CB-1 | 9.615 | 500 |

- `cost_per_mwh` (**$2/MWh on every line**) is **our assumption**: RTS-GMLC has no transmission prices. It is in the range of US transmission-service charges and small next to fuel costs ($22-40/MWh). Ratings are the real RTS values, not scaled to our fleet; they are only checked and reported, not enforced.

## TVA fleet and TVA demand days

Built by `make_tva.py` (`python data/make_tva.py all`; downloads go to the gitignored `data/.cache/`).
You do not need to run it. For the benchmark: `python -m experiments.benchmark --fleet tva --day peak`
or `--all-days`; in code, `load_problem("tva", day=...)` and `src.demand.sample_days(...)`.

| File | What it is |
|---|---|
| `tva_real_plants.json` | Hand-collected list of TVA plants (capacities, units, roles); its cost fields are null |
| `plants_tva.csv` | The 20 dispatchable thermal plants (4 coal, 8 gas CC, 8 gas CT), same columns as `plants.csv` |
| `tva_hourly.csv` | Every usable day of TVA hourly load from EIA-930, July 2018 to June 2026, with its net load |
| `demand_tva/*.csv` | 42 saved days in `demand.csv` format: 5 per season x weekday/weekend, plus `peak` and `min` |
| `demand_tva/index.csv` | The source date, season, day type, peak and minimum of each saved day |
| `tva_meta.json` | Archetype per plant, QAOA block size, day counts (kept / dropped and why) |

### Plants

- Only `uc_role` = `dispatchable_thermal` or `dispatchable_peaker` become rows. Nuclear, hydro and
  Raccoon Mountain pumped storage are not plants here: their real output is taken out of the demand (below).
- The JSON has no costs, so each plant borrows them from an RTS-GMLC unit of the same kind (an
  *archetype*), with the same formulas as `make_data.py`:
  - coal: the RTS unit closest in size to one TVA unit (350 MW or 155 MW class);
  - gas CC and CT: plants sorted by commissioning year, the newest gets the archetype with the lowest
    marginal cost. RTS units with a negative derived no-load cost, and `218_CC_1` (no-load about 10x the
    other CC units), are not used.
- `pmax_mw` = the plant's capacity. `pmin_mw` = the archetype's minimum for **one** unit
  (capacity / units), because a plant can run on a single unit.
- No-load cost, startup cost and ramp rate are scaled by `scale` = capacity / archetype pmax.
  Marginal cost and min up/down times are the archetype's.
- `on_at_start`: coal and CC 1, CT 0.

### Demand

- Source: EIA-930 (Hourly Electric Grid Monitor) six-month bulk BALANCE files, balancing authority `TVA`,
  July 2018 (when generation by fuel starts) to the last complete half-year. Only TVA rows are kept.
- Day = local Data Date, hours 1 to 24 become 0 to 23. EIA's "Adjusted" values are used when present.
- `net_load_mw` = demand - nuclear - hydro (incl. pumped storage, so pumping adds load) - solar - wind -
  storage - geothermal - other. This is what the thermal fleet must cover, and it is the `demand_mw` of the
  saved days. `reserve_mw` = 10% of it.
- Dropped: days without exactly 24 hours (DST changes), with a missing value, with net load <= 0, or with a
  one-hour jump above 30% of the day's maximum. Counts are in `tva_meta.json`.
- `src/demand.py` also leaves out days the fleet cannot cover (max of net load + reserve above the
  17,735 MW capacity): 228 of 2,888 days, mostly summer and winter peaks, when TVA also buys power.
- Bootstrapping: whole real days drawn at random within a season (Dec-Feb winter, Mar-May spring,
  Jun-Aug summer, Sep-Nov fall) and day type (Sat/Sun = weekend). The saved sets use seed 2026.

### QAOA

The QUBO counts capacity in blocks. 50 MW blocks would need far too many qubits for this fleet, so the
TVA fleet uses the smallest block from 100, 150, ... 500 MW that keeps plants + slack bits at 30 or fewer:
100 MW, 5 slack bits, 25 qubits. `Problem.block_view()` rescales the problem so `src/qubo.py` (fixed
50 MW blocks) works unchanged. 25 qubits is still more than a laptop can simulate with this code
(`MAX_LOCAL_QUBITS` = 20), so the benchmark runs only MILP and the rule on this fleet.

EIA-930 data is published by the U.S. Energy Information Administration and is in the public domain.

## License and credit

RTS-GMLC has no separate LICENSE file. Its README carries the data use agreement below, which lets anyone use, copy and distribute the data for any purpose without fee, provided the notice travels with the data and DOE/NREL/ALLIANCE are credited in publications. The files here are derived from RTS-GMLC; credit: **DOE/NREL/ALLIANCE, RTS-GMLC**.

The notice, copied as it appears in the RTS-GMLC README (it ends mid-sentence there):

> **DATA USE DISCLAIMER AGREEMENT** *("Agreement")*
>
> These data ("Data") are provided by the National Renewable Energy Laboratory ("NREL"), which is operated by Alliance for Sustainable Energy, LLC ("ALLIANCE") for the U.S. Department Of Energy ("DOE").
>
> Access to and use of these Data shall impose the following obligations on the user, as set forth in this Agreement. The user is granted the right, without any fee or cost, to use, copy, and distribute these Data for any purpose whatsoever, provided that this entire notice appears in all copies of the Data. Further, the user agrees to credit DOE/NREL/ALLIANCE in any publication that results from the use of these Data. The names DOE/NREL/ALLIANCE, however, may not be used in any advertising or publicity to endorse or promote any products or commercial entities unless specific written permission is obtained from DOE/NREL/ ALLIANCE. The user also understands that DOE/NREL/Alliance is not obligated to provide the user with any support, consulting, training or assistance of any kind with regard to the use of these Data or to provide the user with any updates, revisions or new versions of these Data.
>
> **YOU AGREE TO INDEMNIFY DOE/NREL/ALLIANCE, AND ITS SUBSIDIARIES, AFFILIATES, OFFICERS, AGENTS, AND EMPLOYEES AGAINST ANY CLAIM OR DEMAND, INCLUDING REASONABLE ATTORNEYS' FEES, RELATED TO YOUR USE OF THESE DATA. THESE DATA ARE PROVIDED BY DOE/NREL/Alliance "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL DOE/NREL/ALLIANCE BE LIABLE FOR ANY SPECIAL, INDIRECT OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER, INCLUDING BUT NOT LIMITED TO CLAIMS ASSOCIATED WITH THE LOSS OF DATA OR PROFITS, WHICH MAY RESULT FROM AN ACTION IN CONTRACT, NEGLIGENCE OR OTHER TORTIOUS CLAIM THAT ARISES OUT OF OR IN**
