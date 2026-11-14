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

## What didn't work

-
