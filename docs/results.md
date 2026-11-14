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
| MILP (optimal) | 5 | | 0.00% | 0 | |
| Cheapest-first rule | 5 | | | | |
| MILP (optimal) | 10 | | 0.00% | 0 | |
| Cheapest-first rule | 10 | | | | |

Which rules does cheapest-first break, and why?

## Milestone 3: QUBO check

Command: `python -m experiments.hour_check`

- Hour 12 "Match!": yes / no
- Hours matching the exact best (MILP's previous hour): ___ / 24
- Hours matching (midnight state as previous hour): ___ / 24
- An hour + choice penalized though allowed (> 7 spare blocks): ___
- An hour + choice where minimum outputs exceed demand: ___ · Caught by: ___
- Max-Cut ↔ our QUBO, one sentence: ___

## Milestone 4: hour by hour

Command: `python -m experiments.benchmark` and `python -m experiments.shots_sweep` (**before** tuning)

| Method | Daily cost $ | Gap vs MILP | Rules broken | Wall time |
|---|---|---|---|---|
| QAOA p=1, 200 shots | | | | |
| Random, 200 shots | | | | |

QAOA vs random (valid days out of seeds, mean gap of valid days):

| Shots | QAOA valid | QAOA gap | Random valid | Random gap |
|---|---|---|---|---|
| 5 | | | | |
| 10 | | | | |
| 20 | | | | |
| 50 | | | | |
| 200 | | | | |

What the table tells us / which step of the loop does the work: ___

After tuning (layers, penalty, warm start): ___

## Milestone 5: hardware run record

Also in `results/hardware_runs.csv` (written automatically by `src/hardware.py`).

| Device | Kind (simulator / emulator / QPU) | Job ID | Hour | Shots | p | CX gates | Status | Valid shots | Best-choice share | Queue time |
|---|---|---|---|---|---|---|---|---|---|---|
| Aer | simulator | — | | | 1 | | | | | — |
| ionq:ionq:sim:simulator (forte-1 noise) | simulator | | | | 1 | | | | | |
| ionq:ionq:qpu:forte-1 | QPU | | | ≤ 200 | 1 | | | | | |
| quantinuum:quantinuum:sim:h2-emulator | emulator | | | | 1 | | | | | |

## Timing (honest quantum value)

| Step | 5 plants | 10 plants |
|---|---|---|
| MILP solve | | |
| Hour-by-hour QAOA (simulator), incl. brute-force scoring | | |
| Hardware: submit → result (queue included) | | — |

## What didn't work

-
