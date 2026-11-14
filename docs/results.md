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

After tuning (layers, penalty, warm start): not run yet.

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
