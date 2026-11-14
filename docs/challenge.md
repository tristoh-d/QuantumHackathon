# Challenge: TVA Power Plant Scheduling (Unit Commitment)

Source: [qBraid/tn-quantum-hackathon › 3-tva-plant-scheduling](https://github.com/qBraid/tn-quantum-hackathon/tree/main/3-tva-plant-scheduling)
(snapshot in [`reference/upstream/README.md`](../reference/upstream/README.md); TVA's own words in [`background/`](background/README.md)).

## The problem in one paragraph

Each day TVA decides which plants are **on** for each hour of tomorrow so that the capacity of the plants that are on covers
**demand + a 10% reserve**, at the lowest **whole-day** cost. Big thermal plants (coal, combined-cycle gas) are cheap per MWh but
expensive to start and must stay on/off for hours (**min up / min down**). Peakers start fast but cost more per MWh. The on/off choice
(**unit commitment**) is the hard binary part; how much each plant then produces (**economic dispatch**) is classical and done for us
by the checker (cheapest first).

## Our instance

| | 5-plant (main) | 10-plant (stretch) |
|---|---|---|
| Plants | COAL 350, GAS_CC 350, PEAKER_A 50, PEAKER_B 50, OIL 50 MW | + COAL_MID, COAL_SMALL, GAS_CC_2, PEAKER_C, OIL_2 |
| Demand | 24 h, 280 to 700 MW, reserve = 10% | same curve x 1500/850 |
| Midnight | only COAL on | COAL and COAL_MID on |
| Files | `data/plants.csv`, `data/demand.csv` | `data/plants10.csv`, `data/demand10.csv` |

Data is derived from NREL's RTS-GMLC test system (credit **DOE/NREL/ALLIANCE, RTS-GMLC**; the license notice is in `data/README.md` and must travel with the data).

## Rules (each hour)

1. Every plant that is on makes between `pmin_mw` and `pmax_mw`; total output = demand.
2. Sum of `pmax_mw` of the plants that are on ≥ demand + reserve (spinning reserve).
3. A plant that switches on stays on ≥ `min_up_h`; one that switches off stays off ≥ `min_down_h`.
4. At midnight only COAL is running.
5. Daily cost = startup + no-load + energy costs.

## The hybrid approach the track asks for

- **Classical baseline:** exact MILP (`solve_milp`, provided) and a cheapest-first rule (**TODO 1**).
- **Quantum step:** each hour is a QUBO over 5 plant bits + 3 slack bits (8 qubits). The slack bits turn "capacity ≥ demand + reserve"
  into an equality the QUBO can penalize. Plant costs (**TODO 2**) and the QUBO matrix (**TODO 3**) are ours to write.
- **Loop:** QAOA proposes on/off choices hour by hour; classical code enforces min up/down locks, checks validity, keeps the cheapest
  valid sample, and carries it forward.
- **Hardware:** one hour's 8-qubit circuit on IonQ Forte via qBraid (≤ 200 shots, p = 1), after tuning on Aer and IonQ's noisy simulator.

## Milestones

| # | Milestone | Time | Done when |
|---|---|---|---|
| 1 | Understand it: plot demand, hand-schedule 6 hours | ~1 h | We have a schedule and its cost |
| 2 | Classical baseline: MILP + cheapest-first rule (TODO 1) | 2–3 h | Optimal daily cost and the rule's gap from it |
| 3 | Quantum cost function (TODO 2, TODO 3) + QAOA primer | 1–2 h | Checker prints **Match!** for an hour; one sentence linking Max-Cut cost to ours |
| 4 | Hour by hour with QAOA; QAOA vs random at 5/10/20/50/200 shots × ≥ 5 seeds **before tuning** | 4–5 h | Daily cost vs baseline, broken-rules table, QAOA-vs-random table we can explain |
| 5 | IonQ hardware run (send early, queues take hours); Quantinuum H2 emulator recommended | ~2 h | Job IDs and a hardware-vs-simulator chart |
| 6 | Tell the story: five slides | all weekend | We can walk judges through it in the time given |

## What judges look for

Understanding and clarity count most (why the QUBO works, what the hour-by-hour loop does, what results mean for a utility). Code counts less.

**Due Sunday 9:00 AM:** pitch deck + code ZIP (notebooks run with outputs, IonQ job IDs). Be ready to explain:

- **Solution:** daily cost vs MILP and vs cheapest-first; how often answers were valid; rules broken; hardware vs simulator.
- **Customer & value:** who at a utility would use it, what they use today (a MILP solver), what it takes to trust a new one
  (including hardware queue time). Find a **dated** figure for a utility's yearly fuel + purchased-power cost, say which part we could
  affect, and compute what a 1% change would mean — as a **scenario**, not proven savings, and don't scale the toy day to TVA size.
- **What we learned:** where quantum honestly stands.
- **What didn't work:** say so clearly and explain why (earns points).

## Honest quantum value: questions to answer with our own numbers

- Exact solver time on 5 and 10 plants vs our hour-by-hour QAOA time **including the hardware queue**.
- One hour has 32 choices. How does QAOA compare with checking them all, or with a couple hundred random guesses? Which step of the loop does the work?
- `run_qaoa` scores all 256 bitstrings to tune, and the report checks all 32 choices: count that classical work.
- What does hour-by-hour miss vs planning the whole day?
- What would have to change for quantum to help on unit commitment?
- Reading: Koretsky et al. 2021, [arXiv:2110.12624](https://arxiv.org/abs/2110.12624). What did they conclude?

## Hardware rules

- Tune on Aer → IonQ simulator `ionq:ionq:sim:simulator` with `noise_model="forte-1"` → QPU `ionq:ionq:qpu:forte-1`.
- Only the final tuned circuit on hardware, **≤ 200 shots**, `p = 1` (a few dozen two-qubit gates max).
- Fallback: `aws:ionq:qpu:forte-1` (~1,630 credits / 200 shots). Backup: ask a qBraid mentor about `aws:iqm:qpu:garnet`.
- Free second opinion: `quantinuum:quantinuum:sim:h2-emulator` (accept terms first; label as **emulator**).

## Stretch goals

10 plants (how many slack qubits?) · two hours in one QUBO (16 qubits; GPU sim `qbraid:qbraid:sim:gpu-sv`) · ramp limits
(`ramps=True`, read the checker caveat) · a battery · wind and solar (net load) · drop the slack qubits (unbalanced penalization) ·
a better hour cost (measure where TODO 2's approximation fails).

**Tools worth building:** schedule viewer with broken rules flagged · "what if" tool (demand, fuel prices, reserve) · dashboard comparing
MILP / rule / QAOA on cost and time · visual of how one hour's QAOA answer changes with layers, shots, noise.

# Triston Writeup

# Challenge

We need to decide which power plants we should turn on, and when, so we can meet 'tomorrows' electricity needs at the lowest total cost? 

Comparing the classical solution to the quantum solution should show that the quantum solution has a benefit, if it does not then we need to pivot ideas.

Any tangible benefit such as time saved from classical algorithms to money saved are useful. However it must be taken into consideration that there are plants that have a large startup cost but lower running costs and plants that have a cheap startup cost but expensive running costs. The problem is finding a way to use quantum technology to simulate which plants are worth starting at specific times. 

The main github for the challenge tells us to do the following things

1. Load 5 plants and 24 hours of demand. Schedule 6 hours by hand.
2. Classical baseline: an exact MILP (provided) and a cheapest-first rule (TODO 1).
3. Write one hour as a QUBO (TODO 2, TODO 3) and check it by brute force.
4. Solve one hour with QAOA on a simulator.
5. Run QAOA hour by hour for the whole day. Compare with the baseline.
6. Run one hour on IonQ hardware through qBraid.

We must "Run the cells from top to bottom. A cell marked TODO stops with NotImplementedError until you fill it in. Everything else already works."
