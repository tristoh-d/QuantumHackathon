# Results

Fill these in as we go. Every number should come from a script or notebook run we can reproduce; note the command.

## Milestone 1: hand schedule (hours 0–5)

| Hour | COAL | GAS_CC | PEAKER_A | PEAKER_B | OIL |
|---|---|---|---|---|---|
| 0 | | | | | |
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |
| 4 | | | | | |
| 5 | | | | | |

Cost: $ ___ · Rules broken: ___

## Milestone 2: classical baseline

Command: `python -m experiments.benchmark --skip-qaoa`

| Method | Fleet | Daily cost $ | Gap vs MILP | Rules broken | Solve time |
|---|---|---|---|---|---|
| MILP (optimal) | 5 | 327,924 | 0.00% | 0 | 0.08 s |
| Cheapest-first rule | 5 | 330,594 | +0.81% | 1 | — |
| MILP (optimal) | 10 | 602,139 | 0.00% | 0 | 0.08 s |
| Cheapest-first rule | 10 | 631,461 | +4.87% | 3 | — |

Which rules does cheapest-first break, and why?

- 5 plants: PEAKER_B min up at hour 16 (turned off after 2 h on, needs 3).
- 10 plants: GAS_CC min up at hour 1 (off after 1 h, needs 8); GAS_CC min down at hour 5 (restarted after 4 h off, needs 5); PEAKER_B min up at hour 16 (off after 2 h, needs 3).
- Why: the rule picks each hour on its own and has no memory of how long a plant has been on or off. Every rule it breaks is a min up / min down time. It never breaks demand or reserve, because it checks those inside the hour.

## Milestone 3: QUBO check

Command: `python -m experiments.hour_check`

- Hour 12 "Match!": yes (QUBO picks COAL+GAS_CC+OIL, $18,810; the MILP picked COAL+GAS_CC+PEAKER_A for that hour)
- Hours matching the exact best (MILP's previous hour): 24 / 24
- Hours matching (midnight state as previous hour, `--was-on start`): 24 / 24
- An hour + choice penalized though allowed (> 7 spare blocks): hour 6 (and hour 22), all five plants on: 8 spare blocks, but the 3 slack bits only absorb 7, so the penalty is A·1² even though the checker allows it. On the 10-plant fleet this happens for 1,532 hour + choice pairs, so 3 slack bits are too few there.
- An hour + choice where minimum outputs exceed demand: hours 1–3 (and hour 2 in detail: demand 280 MW), COAL+GAS_CC: minimum outputs 140 + 168 = 308 MW > 280 MW. The capacity penalty is 0 (exactly 7 spare blocks), so the QUBO does not see the problem. · Caught by: the checker (`hour_ok` floor ≤ demand; `check_schedule` reports "minimum outputs exceed demand"). The scheduler also uses `hour_ok` to filter shots, so the choice never reaches the schedule. In practice GAS_CC's startup cost already keeps it from being the cheapest QUBO answer in those hours.
- Max-Cut ↔ our QUBO, one sentence: both are diagonal Ising costs over bits; Max-Cut has only pair (ZZ) terms, one per line, while our QUBO has the same kind of pair terms (from squaring the capacity penalty) plus single-bit terms (plant costs and the linear part of the penalty), so the same QAOA cost layer (RZZ + RZ) and mixer work for both.

## Milestone 4: hour by hour

Command: `python -m experiments.benchmark` and `python -m experiments.shots_sweep` (**before** tuning)

| Method | Daily cost $ | Gap vs MILP | Rules broken | Wall time |
|---|---|---|---|---|
| QAOA p=1, 200 shots | 351,082 | +7.06% | 0 | 3.78 s |
| Random, 200 shots | 351,082 | +7.06% | 0 | 0.12 s |

QAOA and random give the identical schedule here, which is expected. With 5 plants there are only 32 choices per hour, and 200 random shots miss a given choice with probability (31/32)^200 ≈ 0.2%. Both samplers see every choice, both keep the exact best (24 / 24 hours), and both build the same day. The difference shows at fewer shots and on the 10-plant fleet; see the tables below.

(5 plants, seed 7. 10 plants: QAOA $710,528, +18.00%, 0 rules broken, 10.5 s; random $740,091, +22.91%, 3 rules broken, 0.47 s.)

QAOA vs random (valid days out of seeds, mean gap of valid days), 5 plants, p=1, seeds 0–4, `results/shots_sweep.csv`:

| Shots | QAOA valid | QAOA gap | Random valid | Random gap |
|---|---|---|---|---|
| 5 | 0 / 5 | — | 0 / 5 | — |
| 10 | 2 / 5 | +11.82% | 0 / 5 | — |
| 20 | 5 / 5 | +8.11% | 1 / 5 | +10.75% |
| 50 | 5 / 5 | +7.74% | 5 / 5 | +9.44% |
| 200 | 5 / 5 | +7.06% | 5 / 5 | +7.06% |
| 1000 | 5 / 5 | +7.06% | 5 / 5 | +7.06% |

(1000-shot row: `python -m experiments.shots_sweep --shots 1000 --tag 1000shots` → `results/shots_sweep_1000shots.csv`.)

Mean share of valid shots per hour: QAOA ≈ 0.51, random ≈ 0.29. Mean probability of the best choice: QAOA ≈ 0.064, random ≈ 0.031. Mean hours matching the hour's best (of 24): QAOA 5 / 12.6 / 18.4 / 21.8 / 24, random 3 / 5 / 11.4 / 19 / 24.

What the table tells us / which step of the loop does the work:

- At low shot counts (10–50) QAOA is clearly better than random. It roughly doubles the share of valid shots and of the best choice, so it finds valid days with fewer shots.
- At 200 shots both samplers see every one of the 32 choices. The classical step (score every seen choice exactly with `hour_ok` + `hour_cost` and keep the best) then does all the work, and both give exactly the same day.
- The remaining +7.06% gap is not caused by sampling. With 200 shots every hour matches the single-hour best (24 / 24), but the day is still 7% above the MILP. The cause is the hour-by-hour greedy loop: it does not plan ahead for startups and min up / min down times. Better sampling cannot close this gap; a multi-hour formulation is needed.

Where the daily cost comes from: `run_day` builds the schedule hour by hour (keep the cheapest sampled choice that passes `hour_ok`, scored with the exact `hour_cost`), then the checker's `check_schedule` scores the whole day as startup + no-load + energy. Energy uses `dispatch_hour`: every plant that is on makes at least its minimum, and the rest goes to the cheapest plants first. The MILP row is scored by the same checker. Breakdown, 5 plants, 200 shots, seed 7:

| | Total $ | Startup $ | No-load $ | Energy $ |
|---|---|---|---|---|
| MILP | 327,924 | 32,930 | 20,178 | 274,816 |
| Hour by hour | 351,082 | 43,360 | 26,163 | 281,559 |
| Difference | +23,158 | +10,430 | +5,985 | +6,743 |

The schedules differ mainly at hours 5–9. The MILP starts GAS_CC at hour 5 and keeps it on. Hour by hour, GAS_CC's $27,650 startup looks too expensive for one hour, so hours 5–7 are covered with oil and peakers (expensive output plus their own startups and no-load). GAS_CC still has to start at hour 8, when demand is too high for the small plants. The day pays for the small plants and the GAS_CC startup.

### 10-plant fleet: QAOA vs random

Command: `python -m experiments.shots_sweep --fleet 10 --shots 200 1000 --tag fleet10` → `results/shots_sweep_fleet10.csv` (p=1, 3 slack bits, seeds 0–4).

| Shots | QAOA valid | QAOA gap (min–max) | Random valid | Random gap (min–max) |
|---|---|---|---|---|
| 200 | 3 / 5 | +12.30% (+11.09 – +12.91) | 0 / 5 | — |
| 1000 | 5 / 5 | +7.92% (+6.48 – +9.31) | 3 / 5 | +10.65% (+9.49 – +12.01) |

| Shots | Sampler | Valid-shot share | Best-choice share | Hours matching best (of 24) | Time per day |
|---|---|---|---|---|---|
| 200 | QAOA | 0.28 | 0.004 | 11.2 | 9.3 s |
| 200 | Random | 0.09 | 0.001 | 4.0 | 0.4 s |
| 1000 | QAOA | 0.38 | 0.004 | 21.0 | 10.3 s |
| 1000 | Random | 0.17 | 0.001 | 13.4 | 1.5 s |

What this adds:

- With 10 plants there are 1,024 on/off choices, so 200 or 1000 shots no longer see all of them. The sampler now matters, unlike on the 5-plant fleet.
- QAOA gives 2–3× more valid shots and about 4× more best-choice shots than random. It finds more valid days (5 / 5 vs 3 / 5 at 1000 shots, 3 / 5 vs 0 / 5 at 200) and cheaper ones (+7.9% vs +10.7% mean gap at 1000 shots).
- Every invalid day broke a min up / min down time. When no sampled choice meets the locks in an hour, the scheduler drops the locks; more good shots make that less likely.
- Even the best QAOA day (+6.48%) is still far from the MILP, for the same reason as on 5 plants: scheduling one hour at a time.
- The classical price is about 7–20× more wall time than random (simulating QAOA and tuning its angles every hour).

### After tuning (layers, penalty, warm start)

Command: `python -m experiments.tuning_sweep` → `results/tuning.csv` (QAOA only, seeds 0–4, about 20 min). Penalty is scaled against its default A = 2 · max c_i, because A changes from hour to hour. "No warm start" re-runs the coarse angle search every hour instead of starting from the previous hour's angles. The un-tuned rows are the p=1 runs above.

5 plants (200 shots left out: every sampler sees all 32 choices there):

| Setting | Shots | Valid days | Mean gap (valid) | Valid-shot share | Best-choice share | Time per day |
|---|---|---|---|---|---|---|
| Un-tuned (p=1, A = 1×, warm) | 5 / 10 / 20 / 50 | 0 / 2 / 5 / 5 | — / +11.82 / +8.11 / +7.74% | 0.33 / 0.46 / 0.53 / 0.51 | 0.063 | 3 s |
| p=2 | 5 / 10 / 20 / 50 | 0 / 1 / 5 / 5 | — / +8.46 / +9.44 / +7.01% | 0.43 / 0.54 / 0.62 / 0.63 | 0.062 | 7 s |
| p=3 | 5 / 10 / 20 / 50 | 0 / 2 / 5 / 5 | — / +7.86 / +8.22 / +7.53% | 0.47 / 0.61 / 0.65 / 0.63 | 0.079 | 10 s |
| Penalty 0.5× | 5 / 10 / 20 / 50 | 0 / 1 / 5 / 5 | — / +10.02 / +7.97 / +7.88% | 0.34 / 0.44 / 0.53 / 0.51 | 0.064 | 3 s |
| Penalty 3× | 5 / 10 / 20 / 50 | 0 / 2 / 3 / 5 | — / +11.82 / +8.65 / +7.74% | 0.31 / 0.46 / 0.48 / 0.51 | 0.062 | 2.5 s |
| No warm start | 5 / 10 / 20 / 50 | 0 / 0 / 5 / 5 | — / — / +7.27 / +6.30% | 0.25 / 0.40 / 0.48 / 0.49 | 0.060 | 10 s |

10 plants:

| Setting | Shots | Valid days | Mean gap (valid) | Valid-shot share | Best-choice share | Time per day |
|---|---|---|---|---|---|---|
| Un-tuned (p=1, 3 slack bits, warm) | 200 / 1000 | 3 / 5 | +12.30 / +7.92% | 0.28 / 0.38 | 0.004 | 9–10 s |
| p=2 | 200 / 1000 | 4 / 5 | +12.63 / +9.84% | 0.35 / 0.46 | 0.005 | 35–37 s |
| 4 slack bits | 200 / 1000 | 4 / 5 | +12.88 / +8.73% | 0.27 / 0.38 | 0.004 | 26–31 s |
| No warm start | 200 / 1000 | 3 / 5 | +13.09 / +8.38% | 0.26 / 0.37 | 0.004 | 37 s |

(Valid days in the 10-plant table are out of 5 seeds; numbers separated by " / " are per shot count. The valid-days column is for 200 shots; at 1000 shots every setting gives 5 / 5.)

What tuning did:

- **More layers improve the samples, not the day.** p=2 and p=3 raise the valid-shot share (0.62–0.65 vs 0.51–0.53 on 5 plants at 20–50 shots; 0.46 vs 0.38 on 10 plants at 1000). p=3 raises the best-choice share from 0.063 to 0.079. The daily gap does not improve consistently, and the run takes 2–4× longer.
- **The default penalty is the right size.** Halving it or tripling it changes little. Tripling it lowers the valid share at 20 shots (0.48 vs 0.53) and gives fewer valid days (3 / 5 vs 5 / 5).
- **Warm start helps the samples.** Without it the valid share drops (0.25 vs 0.33 at 5 shots) and no 10-shot day is valid. It is also 3× slower, because of the per-hour grid search.
- **4 slack bits on 10 plants** let the QUBO absorb up to 15 spare blocks instead of 7, so far fewer allowed choices are penalized. But the valid share does not rise (0.27 / 0.38 vs 0.28 / 0.38), since the probability is spread over twice as many bitstrings, and the run takes 3× the time. No gain.
- **The cheapest days (no warm start, 50 shots: +6.30%) are below the 7.06% you get from picking every hour's best.** These days do not pick every hour's best (21.2 of 24 hours match on average). A day that matches all 24 hours is exactly the 7.06% day. So a different choice in a few hours happened to save money later in the day. This is the hour-by-hour method's short-sightedness showing up, not a tuning gain.
- **Conclusion:** keep p=1, the default penalty and warm start for the main runs and hardware (p=1 is also what fits on Forte). Tuning can make each shot more useful, but the daily cost is limited by scheduling one hour at a time, not by the sampler.

After tuning (layers, penalty, warm start): ___

## Milestone 5: hardware run record

Also in `results/hardware_runs.csv` (written automatically by `src/hardware.py`).

| Device | Kind (simulator / emulator / QPU) | Job ID | Hour | Shots | p | CX gates | Status | Valid shots | Best-choice share | Queue time |
|---|---|---|---|---|---|---|---|---|---|---|
| Aer | simulator | — | 14 | 200 | 1 | 56 | completed | 54% | 9.0% | — |
| ionq:ionq:sim:simulator (forte-1 noise) | simulator | ionq:ionq:sim:simulator-a99b-qjob-6af87c58c8f5265fb3f1b4f4 | 14 | 200 | 1 | 56 | completed | 50% | 8.0% | |
| ionq:ionq:sim:simulator (forte-1 noise) | simulator | ionq:ionq:sim:simulator-a99b-qjob-6af87ccdc8f5265fb3f1b524 | 14 | 200 | 1 | 56 | completed | 50% | 12.5% | |
| ionq:ionq:qpu:forte-1 | QPU | | | ≤ 200 | 1 | | | | | |
| quantinuum:quantinuum:sim:h2-emulator | emulator | | | | 1 | | | | | |
| ionq:ionq:sim:simulator | simulator | ionq:ionq:sim:simulator-a99b-qjob-6af8811ac8f5265fb3f1b851 | 14 | 200 | 1 | 56 | completed | 60% | 14.0% | 0m 15s |

## Timing (honest quantum value)

| Step | 5 plants | 10 plants |
|---|---|---|
| MILP solve | 0.08 s | 0.08 s |
| Hour-by-hour QAOA (simulator), incl. brute-force scoring | 3.8 s | 10.5 s |
| Hardware: submit → result (queue included) | 15 s (IonQ cloud simulator, not QPU) | — |

Commands: `python -m experiments.benchmark --fleet 5` and `--fleet 10` (seed 7, 200 shots, p=1). Hardware time is from the ionq-sim run in the Milestone 5 table.

## Real TVA data: fleet and demand days

The 5- and 10-plant fleets have one demand day each. To test on many real days, we added:

- **The TVA fleet**, `data/plants_tva.csv`: TVA's 20 coal, gas CC and gas CT plants (17,735 MW), with costs borrowed from RTS-GMLC units of the same kind.
- **TVA demand days**, `data/tva_hourly.csv`: 2,888 real days of TVA hourly load (EIA-930, July 2018 to June 2026), minus TVA's own nuclear, hydro, pumped storage, wind and solar output. What is left (net load) is what the thermal plants must cover. 2,660 of those days fit the fleet's capacity with the 10% reserve; the rest (mostly summer and winter peaks) are left out.
- **Bootstrapping**: days are drawn at random from one season (winter Dec–Feb, spring Mar–May, summer Jun–Aug, fall Sep–Nov) and day type (weekday or weekend).

How the data was built: `data/README.md`. Raw rows of both runs below: `results/tva_classical.csv`, `results/tva_quantum5.csv`.

### Classical: MILP vs cheapest-first rule on the 20-plant TVA fleet

Command: `python -m experiments.tva_benchmark classical` (30 days per season and day type, 240 days, day seed 11). QAOA is not run here: the TVA fleet needs 25 qubits (100 MW blocks + 5 slack bits), and our simulator code keeps tables of 2^n_qubits rows, which needs several GB at 25 qubits.

| Season | Day type | Days | Rule gap mean [95% CI] | Median | Worst | Days with broken rules | MILP time avg / max |
|---|---|---|---|---|---|---|---|
| winter | weekday | 30 | +4.71% [+3.62, +6.02] | +4.25% | +18.49% | 97% | 0.84 / 4.34 s |
| winter | weekend | 30 | +5.29% [+3.96, +6.85] | +3.94% | +17.12% | 93% | 0.57 / 2.63 s |
| spring | weekday | 30 | +5.54% [+4.50, +6.59] | +5.12% | +12.42% | 90% | 0.67 / 2.65 s |
| spring | weekend | 30 | +7.88% [+5.81, +10.28] | +5.11% | +31.40% | 93% | 0.46 / 1.08 s |
| summer | weekday | 30 | +4.20% [+3.63, +4.76] | +4.23% | +7.49% | 93% | 1.24 / 4.68 s |
| summer | weekend | 30 | +4.53% [+4.03, +5.03] | +4.87% | +6.75% | 77% | 1.24 / 4.27 s |
| fall | weekday | 30 | +4.83% [+4.08, +5.64] | +4.48% | +11.55% | 93% | 0.73 / 2.71 s |
| fall | weekend | 30 | +6.46% [+4.63, +8.72] | +5.09% | +27.57% | 93% | 0.61 / 4.87 s |
| **all** | | 240 | **+5.43%** [+4.96, +5.96] | +4.81% | +31.40% | 91% | 0.79 / 4.87 s |

(95% CI: bootstrap of the mean over the days, 2,000 resamples.)

What this shows:

- **The rule is about 5% above the optimum on real TVA days**, close to its +4.87% on the 10-plant fleet and much worse than its +0.81% on the 5-plant fleet. One hand-picked day made the rule look better than it is.
- **It breaks a rule on 91% of days, and every broken rule is a min up or min down time** (in a 60-day sample: 90 min up, 90 min down). Same cause as in Milestone 2: the rule has no memory of the previous hours.
- **Low, flat days are the worst, not peak days.** The gap is more strongly linked to a low daily minimum (correlation −0.54) than to the peak (−0.40). The worst day, 2020-04-04 (spring weekend, net load 2,500–3,200 MW all day), is +31.4%. Energy cost is almost the same as the MILP's ($1.540M vs $1.542M), but the rule starts SHAWNEE_COAL 3 times as load moves around its threshold, at $177k a start: $532k of startups the MILP avoids by leaving the plant off (MILP: 0 startups).
- **Summer is the most predictable** (narrow CI, worst day +7.5%). Spring and fall weekends have the widest spread: their low loads put whole coal plants near the on/off threshold.
- **The MILP stays fast at real scale**: 0.8 s per day on average, 4.9 s at most, for 20 plants × 24 hours.

### Quantum: TVA load shapes on the 5-plant fleet

Command: `python -m experiments.tva_benchmark quantum` (5 days per season and day type, 40 days, day seed 11; QAOA p=1, sampler seed 7). Each TVA day is scaled linearly so the TVA fleet's capacity (17,735 MW) maps to the 5-plant fleet's 850 MW. QAOA stays at 8 qubits but is tested on 40 real load shapes instead of one.

| Method | Shots | Valid days | Gap, all days (mean [95% CI]) | Gap, valid days | Hours matching best (of 24) | Time per day |
|---|---|---|---|---|---|---|
| Cheapest-first rule | — | 25 / 40 | +5.90% [+3.20, +8.86] | +2.41% | — | — |
| QAOA p=1 | 20 | 19 / 40 | +22.62% [+17.79, +27.34] | +15.69% | 14.2 | 3.8 s |
| Random | 20 | 7 / 40 | +27.51% [+24.16, +30.81] | +28.92% | 10.4 | 0.0 s |
| QAOA p=1 | 200 | 40 / 40 | +4.90% [+3.65, +6.22] | +4.90% | 23.8 | 3.7 s |
| Random | 200 | 40 / 40 | +4.60% [+3.45, +5.84] | +4.60% | 23.9 | 0.2 s |

Same day, both valid: at 200 shots QAOA and random give the same cost on 34 of 40 days, QAOA is cheaper on 2 and random on 4 (mean difference +0.30 points against QAOA). At 20 shots only 5 days are valid for both.

What this shows:

- **The Milestone 4 result holds on 40 real days.** At 20 shots QAOA finds a valid day almost 3× as often as random (19 vs 7 of 40) and matches the hour's best choice in more hours (14.2 vs 10.4 of 24). At 200 shots both samplers see nearly all 32 choices each hour, and the classical scoring step decides the day.
- **At 200 shots QAOA is not better than random** (+4.90% vs +4.60%). They differ on only 6 of 40 days. QAOA matches the hour's best slightly less often (23.8 vs 23.9 hours): it puts little probability on some choices, so 200 shots can miss one, while random spreads shots evenly over all 32. A missed hour changes who is on later, so the effect on the day can go either way (QAOA cheaper on 2 days, random on 4).
- **Hour by hour at 200 shots (+4.6–4.9%) beats the cheapest-first rule on average (+5.90%) and never breaks a rule** (40 / 40 valid vs 25 / 40). The rule breaks min up / min down times on 15 days; on the days it is valid, it is cheaper (+2.41%).
- **The gap on the single original day (+7.06%) was on the high side.** Over 40 real shapes the hour-by-hour gap averages about 4.6–4.9%, with a wide spread (CI ±1.3 points).

### Quantum: the same TVA load shapes on the 10-plant fleet

Command: `python -m experiments.tva_benchmark quantum --fleet 10 --shots 200 1000` → `results/tva_quantum10.csv`. The same 40 dates as the 5-plant run, scaled so 17,735 MW maps to the 10-plant fleet's 1,500 MW. QAOA p=1, 3 slack bits, 13 qubits, sampler seed 7.

| Method | Shots | Valid days | Gap, all days (mean [95% CI]) | Gap, valid days | Hours matching best (of 24) | Time per day |
|---|---|---|---|---|---|---|
| Cheapest-first rule | — | 22 / 40 | +4.63% [+3.20, +6.19] | +1.81% | — | — |
| QAOA p=1 | 200 | 38 / 40 | +25.12% [+20.47, +30.29] | +23.89% | 8.4 | 16.2 s |
| Random | 200 | 22 / 40 | +36.31% [+32.24, +40.45] | +39.90% | 3.2 | 0.9 s |
| QAOA p=1 | 1000 | 39 / 40 | +15.18% [+12.90, +17.52] | +15.41% | 19.7 | 17.9 s |
| Random | 1000 | 37 / 40 | +16.53% [+14.28, +18.84] | +16.36% | 15.8 | 2.8 s |

Same day, both valid: at 200 shots (21 days) QAOA is cheaper on 16 and random on 5, mean −7.4 points for QAOA; at 1000 shots (37 days) QAOA is cheaper on 22 and random on 15, mean −0.5 points. At 200 shots, 17 days are valid for QAOA but not for random (1 the other way).

Side by side (same 40 dates; the "enough shots" row is 200 shots on 5 plants and 1000 on 10 plants):

| | 5 plants (8 qubits, 32 choices / hour) | 10 plants (13 qubits, 1,024 choices / hour) |
|---|---|---|
| Rule: valid days, mean gap | 25 / 40, +5.90% | 22 / 40, +4.63% |
| Few shots (20 / 200): QAOA vs random valid days | 19 vs 7 | 38 vs 22 |
| Few shots: QAOA vs random hours matching best | 14.2 vs 10.4 | 8.4 vs 3.2 |
| Enough shots (200 / 1000): QAOA vs random mean gap | +4.90% vs +4.60% | +15.18% vs +16.53% |
| Enough shots: hours matching best | 23.8 vs 23.9 | 19.7 vs 15.8 |
| QAOA time per day | 3.7 s | 16–18 s |

What the comparison shows:

- **QAOA's advantage grows with the fleet.** On 5 plants, 200 shots see all 32 choices and QAOA ties random. On 10 plants, 1000 shots do not see all 1,024 choices, and QAOA matches the hour's best in 19.7 hours vs 15.8 for random. At 200 shots the difference is large: 38 vs 22 valid days, and 7 points cheaper on the days both are valid.
- **But on 10 plants hour by hour is far from the optimum on real days.** At 1000 shots QAOA averages +15.2%, about twice its +7.92% on the single original 10-plant day (Milestone 4, 5 seeds). The original day was an easy one for the 10-plant fleet; real shapes cost the greedy loop much more. On the same dates the 10-plant QAOA gap is 10.4 points higher than the 5-plant one.
- **The cheapest-first rule beats every sampled method on cost** (+4.63% over all days), but it breaks min up / min down times on 18 of 40 days. QAOA at 1000 shots is valid on 39 of 40. The rule's gaps on the two fleets go together (correlation 0.67 per day): the same real shapes are hard for it on both.
- **No season stands out for invalid QAOA days** (2 at 200 shots, 1 at 1000). Random's invalid days at 200 shots are mostly summer (9 of 18) and winter (5); we have not checked why.
- **Takeaway:** QAOA's sampling advantage only shows up once the choice space is too big to cover with shots (10 plants). At that size, scheduling one hour at a time leaves 15% on the table. A multi-hour formulation matters more than a better sampler.

### Simulated backends: noise and depth on TVA load shapes (5-plant fleet)

Command: `python -m experiments.tva_sims run --config <name>` for each config (we ran the 7 in parallel), then `python -m experiments.tva_sims summary` → `results/tva_sims_<config>.csv`. Same 40 TVA dates as above, scaled to the 5-plant fleet; every day scored against its own MILP; sampler seed 7; 20 and 50 shots (at 200 shots every sampler sees all 32 choices, see above).

In every config the angles are tuned on the noise-free statevector, as before a hardware run. Only the distribution the shots are drawn from changes. Noisy configs use an Aer density-matrix simulation of the circuit transpiled to rz / sx / x / cx (56 CX at p=1), with depolarizing gate noise and readout error:

| Config | 1-qubit error | 2-qubit error | Readout error | Distance from ideal distribution (hour 12, p=1) |
|---|---|---|---|---|
| ideal | 0 | 0 | 0 | 0 |
| forte (near IonQ Forte-1's published figures) | 0.02% | 0.4% | 0.5% | 0.05 |
| noisy | 0.1% | 2% | 2% | 0.21 |
| vnoisy | 0.2% | 5% | 3% | 0.38 |

(Distance = total variation distance between the noisy and the ideal probabilities over the 256 bitstrings.)

| Config | Shots | Valid days | Gap vs MILP, all days (mean [95% CI]) | Gap, valid days | Valid-shot share | Best-choice share | Hours matching best (of 24) |
|---|---|---|---|---|---|---|---|
| ideal p=1 | 20 | 19 / 40 | +22.62% [+17.79, +27.34] | +15.69% | 0.34 | 0.051 | 14.2 |
| ideal p=2 | 20 | 25 / 40 | +22.60% [+17.38, +28.23] | +13.68% | 0.49 | 0.080 | 15.4 |
| forte p=1 | 20 | 16 / 40 | +24.28% [+18.96, +29.99] | +21.90% | 0.34 | 0.048 | 13.7 |
| forte p=2 | 20 | **32 / 40** | **+16.55%** [+12.71, +20.59] | +13.77% | 0.50 | 0.072 | 15.8 |
| noisy p=1 | 20 | 17 / 40 | +23.84% [+19.03, +28.96] | +17.05% | 0.30 | 0.042 | 12.7 |
| vnoisy p=1 | 20 | 12 / 40 | +23.08% [+18.11, +28.32] | +15.02% | 0.27 | 0.037 | 13.2 |
| random | 20 | 7 / 40 | +27.51% [+24.16, +30.81] | +28.92% | 0.19 | 0.031 | 10.4 |
| ideal p=1 | 50 | 37 / 40 | +8.82% [+6.97, +10.90] | +8.29% | 0.45 | 0.051 | 20.4 |
| ideal p=2 | 50 | 40 / 40 | +5.98% [+4.42, +7.73] | +5.98% | 0.67 | 0.081 | 22.7 |
| forte p=1 | 50 | 36 / 40 | +8.00% [+6.32, +9.97] | +8.17% | 0.44 | 0.047 | 19.7 |
| forte p=2 | 50 | 40 / 40 | **+5.61%** [+4.24, +7.09] | +5.61% | 0.61 | 0.072 | 22.2 |
| noisy p=1 | 50 | 39 / 40 | +8.18% [+6.29, +10.35] | +7.44% | 0.40 | 0.042 | 20.2 |
| vnoisy p=1 | 50 | 37 / 40 | +7.61% [+6.23, +9.02] | +7.62% | 0.37 | 0.037 | 19.9 |
| random | 50 | 30 / 40 | +8.56% [+7.22, +10.18] | +7.34% | 0.30 | 0.031 | 20.5 |

Same day, both valid, against ideal p=1 at 50 shots: p=2 is cheaper on 23 of 37 days (mean −2.32 points), forte p=2 on 23 of 37 (−2.58). The p=1 noise levels are a coin flip against ideal p=1 (forte 15 cheaper / 18 dearer, noisy 18 / 16, vnoisy 19 / 14; means within ±1 point).

Time per day is not in the table: the 7 configs ran at the same time and slowed each other down (ideal p=1 took 11.9 s per day here vs 3.7 s alone). Noisy runs add an 8-qubit density-matrix simulation per hour, about 0.05–0.1 s.

What this shows:

- **Noise wears down QAOA's sample quality step by step, toward random.** At p=1 the valid-shot share goes 0.34 (ideal) → 0.34 (forte) → 0.30 (noisy) → 0.27 (vnoisy) → 0.19 (random), and the best-choice share 0.051 → 0.048 → 0.042 → 0.037 → 0.031. Even at 5% two-qubit error, QAOA still finds more valid 20-shot days than random (12 vs 7).
- **Forte-level noise costs almost nothing.** The valid-shot share is unchanged and the best-choice share drops by 6%. Its 20-shot valid days (16 vs 19) and 50-shot gap (+8.00% vs +8.82%) are inside run-to-run spread. A Forte-1 run of this circuit should look like the simulator.
- **Depth helps more than noise hurts.** p=2 has twice the CX gates but raises the valid share to 0.49–0.67 and the best-choice share to 0.07–0.08, with or without Forte noise. At 50 shots both p=2 configs are valid on 40 / 40 days and are the only configs clearly better than random (+5.6–6.0% vs +8.56%; their CIs only just overlap random's, whose lower end is +7.22%). At 20 shots forte p=2 has the most valid days (32 vs 25 for ideal p=2). That difference comes from one sampler seed; we would not read it as noise helping.
- **At 50 shots, p=1 QAOA is no better than random on daily cost** (+7.6–8.8% vs +8.56%, overlapping CIs), even though its samples are better. 50 shots on 32 choices already finds the hour's best most of the time (20.4 vs 20.5 hours for ideal p=1 vs random). The classical scoring step does most of the work, as in Milestone 4.
- **Compared with the MILP**, the best simulated setting (p=2, 50 shots) is +5.6–6.0% on real days. That is close to the 200-shot hour-by-hour gap (+4.6–4.9%) and to the cheapest-first rule (+5.90%, but valid on only 25 / 40 days). The remaining gap is the hour-by-hour method, not the backend.

## What didn't work

-
