# Demo Notes

Five slides (track README, milestone 6). Due **Sunday 9:00 AM** with the code ZIP. Understanding and clarity count most.
Pull numbers from [`docs/results.md`](../docs/results.md).

## Slide 1: The customer and the problem
- Who schedules the plants at a utility, and what they use today (a MILP solver like ours).
- Unit commitment vs economic dispatch, in one picture. Pizzeria analogy if useful.
- What it would take for them to trust a new method (including hardware queue time).

## Slide 2: Our formulation
- One hour as a QUBO: 5 plant bits + 3 slack bits; why slack turns "≥" into an equality.
- How the primer's Max-Cut cost relates to ours (one sentence).
- The hour-by-hour loop: what's quantum, what's classical.

## Slide 3: Results
- Daily cost: MILP vs cheapest-first vs QAOA vs random; gap and rules broken.
- How often answers were valid. QAOA-vs-random table across shots and seeds.
- Hardware vs simulator chart (labeled simulator / emulator / QPU), job IDs.

## Slide 4: Value scenario
- Dated, sourced figure for a utility's yearly fuel + purchased-power cost.
- Which part our method could affect; what a 1% change would mean. Call it a **scenario**, not proven savings. Don't scale the toy day to TVA.

## Slide 5: What we learned (honest quantum value)
- Time: MILP vs hour-by-hour QAOA including queue; classical work hidden inside the QAOA loop.
- What hour-by-hour misses vs whole-day planning.
- What didn't work, and why.
- What would have to change for quantum to help (Koretsky et al. 2021).

## Demo flow
1. `notebooks/starter.ipynb` sections 1–2 (demand plot, MILP schedule).
2. `python -m experiments.hour_check` → "Match!".
3. Section 6 comparison chart.
4. Hardware chart from `results/`.

## Likely judge questions
- Why does your QUBO's minimum correspond to the best on/off choice? When doesn't it?
- If random guessing does as well, what is QAOA adding?
- Why does hour-by-hour cost more than the MILP?
