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
| ionq:ionq:qpu:forte-1 | QPU | — | | ≤ 200 | 1 | | not run (1,630 credits needed, 491 available) | | | |
| quantinuum:quantinuum:sim:h2-emulator | emulator | — | | | 1 | | not run | | | |
| ionq:ionq:sim:simulator | simulator | ionq:ionq:sim:simulator-a99b-qjob-6af8811ac8f5265fb3f1b851 | 14 | 200 | 1 | 56 | completed | 60% | 14.0% | 0m 15s |
| aws:rigetti:qpu:cepheus-1-108q | QPU | aws:rigetti:qpu:cepheus-1-108q-a99b-qjob-6af8ea1dc8f5265fb3f212c2 | 14 | 200 | 1 | 56 | completed | 6% | 0.5% | 6m 33s |
| aws:rigetti:qpu:cepheus-1-108q | QPU | aws:rigetti:qpu:cepheus-1-108q-a99b-qjob-6af900e4c8f5265fb3f21d91 | 14 | 200 | 1 | 56 | completed | 7% | 3.0% | 4m 25s |

### Real hardware: Rigetti Cepheus-1 (2026-11-14)

We could not afford IonQ Forte. Through AWS it costs 30 + 8 credits per shot, so 200 shots cost 1,630 credits, and we had 491. The direct IonQ route was unavailable. We ran the same tuned p=1 circuit on Rigetti Cepheus-1 (108 superconducting qubits, through AWS: 30 + 0.0425 credits per shot, about 38.5 credits per 200-shot run). We also ran a shallow Max-Cut circuit as a calibration check. Both runs together used 77 credits.

| Circuit (200 shots, p=1) | Measure | Aer (ideal) | Rigetti QPU | Random guessing |
|---|---|---|---|---|
| Max-Cut primer, 6 nodes, 14 CX | Average cut (out of 7) | 5.08 | **3.94** | 3.5 |
| | Shots with the best cut | 28.5% | **5.5%** | — |
| UC fleet 5, hour 14, 8 qubits, 56 CX | Valid shots | 54% | **6%** | 12.5% (4 / 32 choices) |
| | Best-choice share | 9.0% | **0.5%** | 3.1% (1 / 32) |

- **The shallow circuit still shows some signal.** Max-Cut on hardware is above random (3.94 vs 3.5), but noise removes most of the ideal gain.
- **The UC circuit is worse than random guessing.** At 56 CX (4× the Max-Cut depth), noise destroys the QAOA signal. The four plant qubits read out "on" in only 38–43% of shots. That bias pushes samples toward too little capacity, which makes them invalid.
- **A Forte-noise simulator does not show this collapse.** The same circuit on IonQ's cloud simulator with the `forte-1` noise model gave 50% valid shots and an 8.0–12.5% best-choice share. That is close to ideal Aer (54%, 9.0%). Our own noise study ([noise and depth](#simulated-backends-noise-and-depth-on-tva-load-shapes-5-plant-fleet)) also finds Forte-level noise costs almost nothing. So the failure is tied to this device's noise level, not to the circuit itself. This is a prediction only: we have no Forte QPU run to confirm it.
- **Turnaround:** 6 m 33 s from submit to result for one hour on the QPU, against 0.08 s for the MILP to solve the whole day. A 24-hour schedule built hour by hour on this QPU would take about 2.6 hours of queue time alone.
- **What this means:** on superconducting hardware today, the hour-by-hour QUBO at p=1 is too deep to beat random sampling. The classical MILP stays the right tool. The hybrid needs a lower-noise device (Forte, trapped ions with all-to-all connections, so fewer gates after compiling) or a shallower QUBO.

Job IDs: Max-Cut `aws:rigetti:qpu:cepheus-1-108q-a99b-qjob-6af8e9ffc8f5265fb3f212ac` (26 s from submit to result), UC as in the table above. Counts are in `results/counts/`. Chart: `results/hardware_hour14_fleet5_rigetti-qpu-aws.png`. Command: `python -m experiments.qbraid_driver run --task {uc,maxcut} --device rigetti-qpu-aws --i-am-sure`.

## Timing (honest quantum value)

| Step | 5 plants | 10 plants |
|---|---|---|
| MILP solve | 0.08 s | 0.08 s |
| Hour-by-hour QAOA (simulator), incl. brute-force scoring | 3.8 s | 10.5 s |
| Hardware: submit → result (queue included) | 15 s (IonQ cloud simulator); 6 m 33 s (Rigetti Cepheus-1 QPU) | — |

Commands: `python -m experiments.benchmark --fleet 5` and `--fleet 10` (seed 7, 200 shots, p=1). Hardware times are from the ionq-sim and Rigetti runs in the Milestone 5 table.

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

## Where MILP struggles

Background and sources: docs/milp_hard_cases.md. Commands: `python -m experiments.milp_hardness milp` → `results/hardness_milp.csv` (n = 10–50, 5 seeds, 30 s limit); `python -m experiments.milp_hardness quantum --family <family>` → `results/hardness_quantum_<family>.csv` (exact statevector, n = 8–22); `python -m experiments.milp_hardness summary` prints the tables below. The n = 22 quantum rows have 3 seeds, not 5 (the run was stopped there). MILP times were measured with four experiments sharing the CPU, so the node counts are the more robust measure.

### MILP (HiGHS) effort vs size

| Family | n | MILP vars | Median time | Median nodes | Max nodes | Timeouts |
|---|---|---|---|---|---|---|
| market_split | 10 | 10 | 0.02 s | 3 | 16 | 0 / 5 |
| market_split | 15 | 15 | 0.17 s | 31 | 174 | 0 / 5 |
| market_split | 20 | 20 | 0.93 s | 1,572 | 4,273 | 0 / 5 |
| market_split | 25 | 25 | 9.32 s | 5,992 | 33,543 | 0 / 5 |
| market_split | 30 | 30 | 30.02 s | 2,636 | 50,827 | 3 / 5 |
| market_split | 35–50 | 35–50 | 30.02 s | 0 | 0 | 5 / 5 each |
| interaction | 10 | 55 | 0.15 s | 1 | 1 | 0 / 5 |
| interaction | 15 | 113 | 0.46 s | 1 | 7 | 0 / 5 |
| interaction | 20 | 200 | 3.08 s | 13 | 22 | 0 / 5 |
| interaction | 25 | 307 | 19.03 s | 230 | 303 | 0 / 5 |
| interaction | 30 | 444 | 30.03 s | 621 | 671 | 4 / 5 |
| interaction | 35–50 | 606–1,222 | 30.04 s | 2–207 | 2–294 | 5 / 5 each |
| symmetric | 10–50 | 10–50 | 0.01–0.09 s | 1 | 1 | 0 / 5 each |

(Market split at n ≥ 35: 0 nodes means the 30 s ran out before branching started.)

### QAOA vs random vs SA: exact probability that one shot is optimal

Geometric mean over seeds. "sa" is the share of 1,000 annealing runs (1,000 sweeps each, same QUBO) that end at the optimum; the bracket counts the instances where any run found it. "transfer" reuses median angles from a smaller size, without per-instance tuning.

Market split:

| n | MILP time / nodes | random | qaoa_p1 | qaoa_p2 | qaoa_p3 | qaoa_p1_transfer | sa |
|---|---|---|---|---|---|---|---|
| 8 | 0.002 s / 0 | 3.91e-03 | 4.27e-03 | 9.60e-03 | 8.49e-03 | — | 0.196 (5/5 inst.) |
| 10 | 0.022 s / 3 | 9.77e-04 | 9.68e-04 | 2.57e-03 | 2.55e-03 | 8.34e-04 | 0.057 (5/5 inst.) |
| 12 | 0.067 s / 13 | 2.44e-04 | 4.27e-04 | 7.33e-04 | 7.68e-04 | 3.89e-04 | 0.017 (5/5 inst.) |
| 14 | 0.159 s / 55 | 6.10e-05 | 8.59e-05 | 1.90e-04 | 1.95e-04 | 5.31e-05 | 0.008 (5/5 inst.) |
| 16 | 0.273 s / 235 | 1.53e-05 | 1.71e-05 | 4.38e-05 | 3.99e-05 | 1.51e-05 | 0.004 (5/5 inst.) |
| 18 | 0.623 s / 793 | 3.81e-06 | 4.95e-06 | 1.25e-05 | 1.30e-05 | 4.10e-06 | 0.001 (4/5 inst.) |
| 20 | 2.579 s / 1,572 | 9.54e-07 | 1.13e-06 | 3.13e-06 | 2.90e-06 | 8.43e-07 | 0.001 (3/5 inst.) |
| 22 | 5.914 s / 6,105 | 2.38e-07 | 3.97e-07 | 8.86e-07 | 9.22e-07 | 3.79e-07 | 0.000 (0/3 inst.) |

Interaction:

| n | MILP time / nodes | random | qaoa_p1 | qaoa_p2 | qaoa_p3 | qaoa_p1_transfer | sa |
|---|---|---|---|---|---|---|---|
| 8 | 0.029 s / 1 | 4.49e-03 | 8.58e-03 | 6.68e-03 | 1.73e-02 | — | 0.157 (5/5 inst.) |
| 10 | 0.043 s / 1 | 9.77e-04 | 2.33e-03 | 3.80e-03 | 4.13e-03 | 7.87e-04 | 0.071 (5/5 inst.) |
| 12 | 0.067 s / 1 | 2.44e-04 | 6.14e-04 | 9.92e-04 | 1.13e-03 | 6.59e-04 | 0.027 (5/5 inst.) |
| 14 | 0.165 s / 1 | 7.01e-05 | 1.86e-04 | 2.91e-04 | 3.53e-04 | 1.99e-04 | 0.010 (5/5 inst.) |
| 16 | 0.386 s / 5 | 1.53e-05 | 4.29e-05 | 6.74e-05 | 8.39e-05 | 4.56e-05 | 0.002 (4/5 inst.) |
| 18 | 0.536 s / 7 | 3.81e-06 | 1.11e-05 | 1.19e-05 | 1.58e-05 | 1.17e-05 | 0.001 (5/5 inst.) |
| 20 | 3.260 s / 13 | 1.19e-06 | 3.53e-06 | 3.74e-06 | 5.01e-06 | 3.71e-06 | 0.000 (1/5 inst.) |
| 22 | 3.963 s / 20 | 2.84e-07 | 9.43e-07 | 9.81e-07 | 1.36e-06 | 9.89e-07 | 0.000 (0/3 inst.) |

Symmetric:

| n | MILP time / nodes | random | qaoa_p1 | qaoa_p2 | qaoa_p3 | qaoa_p1_transfer | sa |
|---|---|---|---|---|---|---|---|
| 8 | 0.024 s / 1 | 1.37e-02 | 2.35e-02 | 3.16e-02 | 2.97e-02 | — | 0.169 (5/5 inst.) |
| 10 | 0.003 s / 1 | 7.90e-03 | 1.39e-02 | 2.06e-02 | 2.37e-02 | 1.44e-02 | 0.231 (5/5 inst.) |
| 12 | 0.004 s / 1 | 4.70e-03 | 6.64e-03 | 1.34e-02 | 1.64e-02 | 3.98e-03 | 0.158 (5/5 inst.) |
| 14 | 0.008 s / 1 | 2.59e-03 | 3.22e-03 | 6.84e-03 | 7.16e-03 | 2.32e-03 | 0.099 (5/5 inst.) |
| 16 | 0.033 s / 1 | 1.97e-03 | 3.30e-03 | 7.22e-03 | 7.12e-03 | 1.99e-03 | 0.044 (5/5 inst.) |
| 18 | 0.031 s / 1 | 2.36e-05 | 3.14e-05 | 6.37e-05 | 8.29e-05 | 2.82e-05 | 0.003 (2/5 inst.) |
| 20 | 0.024 s / 1 | 1.83e-04 | 3.05e-04 | 5.00e-04 | 4.45e-04 | 3.09e-04 | 0.004 (5/5 inst.) |
| 22 | 0.119 s / 1 | 5.75e-06 | 2.53e-06 | 6.95e-06 | 6.31e-06 | 2.10e-06 | 0.000 (1/3 inst.) |

How fast p_opt falls (halvings per added plant, fit of log2 p_opt vs n; lower is better):

| Family | random | qaoa_p1 | qaoa_p2 | qaoa_p3 | qaoa_p1_transfer |
|---|---|---|---|---|---|
| market_split | 1.000 | 0.977 | 0.964 | 0.958 | 0.977 |
| interaction | 0.990 | 0.943 | 0.954 | 0.979 | 0.856 |
| symmetric | 0.768 | 0.851 | 0.803 | 0.815 | 0.928 |

What this shows:

- **No result here shows quantum beating classical.** The sizes where the MILP struggles (n ≥ 25–30 for market split and interaction) are past what we can simulate exactly (n ≤ 22). At n ≤ 22 the MILP finds the proven optimum in 6 s or less.
- **The MILP struggles where the literature says it should, except on symmetry.** Market split needs thousands of nodes from n = 20 and times out from n = 30. Interaction times out from n = 30 (its McCormick form has about n²/2 variables). Symmetric never needs more than 1 node: HiGHS handles that symmetry by itself.
- **QAOA beats random by a roughly fixed factor, not a growing one.** At p=3 it is about 2–4× (market split) and 4–5.5× (interaction) more likely than random to return the optimum, at every size. The fitted slopes are only slightly below random's (0.96 vs 1.00 halvings per plant on market split), so extra plants still cost QAOA almost as much as they cost random guessing. On symmetric, QAOA's probability falls faster than random's.
- **The numbers are too small to use.** At n = 22, p_opt ≈ 1e-6 means about 4–5 million shots for a 99% chance of seeing the optimum, plus 3–5 minutes of classical angle tuning per instance (transferred angles do about as well as p=1 tuned ones, so tuning could be skipped).
- **Simulated annealing on the same QUBO is far ahead per attempt** (0.23–0.001 per run vs 1e-2–1e-6 per shot), but it also stops finding the optimum at n = 20–22 (0 of 3 market split and interaction instances at n = 22, in 1,000 runs). Neither sampler is a substitute for the MILP at these sizes.
- **Where QAOA does win, it wins over random sampling and the simple rule, not over the MILP:** more valid days and cheaper days than random on the 10-plant fleet (above), and valid on 39 / 40 TVA days vs 22 / 40 for the cheapest-first rule, which is still cheaper on cost.

## Where MILP struggles: exact, noise-free QAOA vs MILP, SA and random

Background and sources: [docs/milp_hard_cases.md](milp_hard_cases.md). Three one-hour UC scenarios are built so that LP-based branch and bound has a hard time. Each one is generated as both a MILP and a QUBO, with one qubit per plant and no slack qubits:

- **market_split**: must-take generation, no curtailment. m zones (m = 2 up to 19 plants, 3 at 20–29, 4 at 30–39 …), each balanced exactly. This is the Cornuéjols–Dawande family.
- **interaction**: pairwise plant costs of mixed sign (shared pipeline, crews, transmission), with exactly n/2 units on. The MILP needs a product variable per pair.
- **symmetric**: three unit types with many identical copies, demand matched exactly.

Commands: `python -m experiments.milp_hardness milp` (5 seeds per size, 30 s limit) and `quantum` (5 seeds per size, n = 8–22), then `summary`. The QAOA numbers are **exact**: full-statevector probabilities with no noise model and no shot sampling (`src/exact_qaoa.py`, checked against Qiskit's `Statevector`). Every instance's brute-force optimum equals the MILP optimum. The four sweeps ran in parallel, so the times are inflated. Node counts are the cleaner measure.

### MILP effort grows fast on market split

| Family | n = 10 | 15 | 20 | 25 | 30 | 35–50 |
|---|---|---|---|---|---|---|
| market_split: median nodes / time | 3 / 0.02 s | 31 / 0.17 s | 1,572 / 0.9 s | 5,992 / 9.3 s | 3 / 5 time out | 5 / 5 time out, **no schedule found at all** |
| interaction: median nodes / time (MILP variables) | 1 / 0.15 s (55) | 1 / 0.5 s (113) | 13 / 3.1 s (200) | 230 / 19 s (307) | 4 / 5 time out (444) | all time out (606–1,222) |
| symmetric: median nodes / time | 1 / 0.02 s | 1 | 1 | 1 | 1 | 1 / ≤ 0.13 s |

- **Market split is the real MILP-hard case.** Nodes grow about 3–50× for every 5 added plants. From 35 plants (5 zones) up, HiGHS does not even find one feasible schedule in 30 s.
- **Interaction is hard for a different reason.** Branching stays small (≤ 671 nodes). The linearized LP grows with n² (1,222 variables at 50 plants), and from 30 plants the 30 s run out after only a few hundred nodes, so each node is expensive.
- **Symmetry did not hurt HiGHS at all.** Every instance up to 50 plants solved at the root node. Modern presolve and symmetry handling take care of it.

### Exact per-shot chance of the optimum (geometric mean of 5 instances)

| Family | n | MILP | Random | QAOA p=1 | QAOA p=2 | QAOA p=3 | QAOA p=1, transferred angles | SA (1,000 sweeps), per run |
|---|---|---|---|---|---|---|---|---|
| market_split | 14 | 0.16 s | 6.1e-5 | 8.6e-5 | 1.9e-4 | 2.0e-4 | 5.3e-5 | 0.008 |
| market_split | 18 | 0.62 s | 3.8e-6 | 5.0e-6 | 1.3e-5 | 1.3e-5 | 4.1e-6 | 0.001 (4/5 inst.) |
| market_split | 22 | 3.6 s | 2.4e-7 | 3.5e-7 | 8.6e-7 | 8.0e-7 | 3.5e-7 | 0 (0/5 inst.) |
| interaction | 14 | 0.17 s | 7.0e-5 | 1.9e-4 | 2.9e-4 | 3.5e-4 | 2.0e-4 | 0.010 |
| interaction | 18 | 0.54 s | 3.8e-6 | 1.1e-5 | 1.2e-5 | 1.6e-5 | 1.2e-5 | 0.001 |
| interaction | 22 | 2.5 s | 2.7e-7 | 8.5e-7 | 8.9e-7 | 1.2e-6 | 8.9e-7 | 0 (0/5 inst.) |
| symmetric | 14 | 0.01 s | 2.6e-3 | 3.2e-3 | 6.8e-3 | 7.2e-3 | 2.3e-3 | 0.099 |
| symmetric | 22 | 0.09 s | 1.8e-5 | 2.1e-5 | 5.6e-5 | 5.8e-5 | 1.9e-5 | 0.007 (3/5 inst.) |

How fast the chance falls (fit of log₂ p_opt against n, n = 8–22; 1.0 = it halves with every added plant, like random guessing with one optimum):

| Family | Random | QAOA p=1 | p=2 | p=3 |
|---|---|---|---|---|
| market_split | 1.00 | 0.98 | 0.97 | 0.97 |
| interaction | 0.99 | 0.95 | 0.96 | 0.99 |
| symmetric | 0.70 | 0.73 | 0.68 | 0.68 |

At n = 22 the classical angle tuning took 160–250 s per instance (QAOA p=1–3). The MILP took 2.5–3.6 s.

What this shows:

- **No quantum advantage here, even with a perfect noise-free simulator.** QAOA beats random by a constant factor: 1.5–3.6× on market split and 3–4.5× on interaction at n = 22. But its success chance halves with almost every added plant, just like random guessing (0.95–0.99 vs 1.00 halvings per plant). For a 99% chance of seeing the optimum at 22 plants, QAOA p=2 needs about 5.4 million shots on market split. The MILP proves the optimum in 3.6 s.
- **The penalty is the problem.** Exact equality constraints make the penalty dwarf the cost, so the QAOA landscape is mostly about feasibility. On market split, almost no probability lands on feasible schedules (p_feasible ≈ 0 at n = 22). On interaction, QAOA raises the feasible share from 0.17 (random) to 0.51–0.71, but the optimum among the feasible schedules is still rare.
- **Depth helps a little.** p=2 or p=3 doubles to triples p_opt over p=1 on market split and symmetric, but does not change the slope.
- **Angle transfer works.** Median angles from the next smaller size give the same p_opt as per-instance tuning at p=1 (for example 8.9e-7 vs 8.5e-7 for interaction at n = 22), with zero tuning time. Larger qubit counts (gpu-sv) can use the same transfer.
- **Single-flip SA on the same QUBO also fails at 22 plants** on market split and interaction (0 optimal runs out of 1,000 on every instance). The feasible schedules are separated by penalty barriers that single bit flips cannot cross. So "QAOA vs SA" on these penalty QUBOs is a contest between two weak methods. The MILP, which handles the constraints directly, wins clearly at these sizes.
- **Where the MILP does break (market split ≥ 30 plants), QAOA would need far more than the qubits we can simulate exactly.** Extrapolating the slope, p_opt at 35 plants is about 1e-10 (5e-11 at p=1). The interesting question is whether a constraint-preserving mixer (for example an XY mixer that keeps "exactly k on") changes the slope. We have not tested that.

## What didn't work

-
