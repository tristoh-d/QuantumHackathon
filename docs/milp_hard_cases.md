# Where MILP struggles, and whether QAOA can do better there

The MILP is our exact baseline and solves every scheduling day we have in under 5 s (docs/results.md). We searched for unit-commitment scenarios where a MILP solver (HiGHS, through `scipy.optimize.milp`) is known to struggle. We then tested QAOA there with **exact, noise-free simulation**: full statevector probabilities, no noise model, and no shot noise wherever the state fits in memory. Results: docs/results.md, section "Where MILP struggles". Code: `src/hard_instances.py`, `src/hard_milp.py`, `src/exact_qaoa.py`, `src/anneal.py`, `experiments/milp_hardness.py`.

## Why MILP is usually strong on unit commitment

A MILP solver solves the LP relaxation (on/off variables allowed to be fractional) and branches on fractional variables. It is fast when the LP bound is close to the integer optimum. Standard unit commitment has this property: costs are linear, min up/down times have tight textbook formulations, and demand is met with plenty of flexibility (any mix of plants with enough capacity works). Our runs show it: 20 TVA plants × 24 hours in 0.8 s on average.

The MILP becomes slow when the LP bound is weak, or when many branches look alike. Three UC situations do that:

## 1. Must-take generation with no curtailment ("market split")

**Scenario.** Several zones (or hours) must be balanced **exactly**: no curtailment, no spare band, and every committed plant runs at a fixed block output (for example must-run contracts or fixed-output units). Each zone's committed blocks must add up to its demand.

**Why it is hard for MILP.** This is the market-split problem of Cornuéjols and Dawande, a class of small 0-1 programs they showed to be extremely hard for branch and bound and branch and cut. With m equality rows and n = 10(m−1) variables, instances with 6–7 rows and 50–60 variables were out of reach in their paper. The LP relaxation is almost always feasible (fractional plants can match any demand), so the bound gives no guidance. It appears in MIPLIB as the `markshare` instances.

**The classical counter-argument.** Lattice basis reduction (Aardal, Bixby, Hurkens, Lenstra and Smeltink, 2000) solves these instances up to 7 equations and 60 variables. The family is hard for **LP-based** MILP, not for every classical method.

**For QAOA.** Equality constraints need no slack qubits: one qubit per plant, penalty Σ (aᵀx − r)². But feasible schedules are rare and isolated. Changing one plant breaks the balance, so any method that changes one bit at a time (SA, and the QAOA mixer) must cross large penalty barriers.

## 2. Pairwise interaction costs (nonconvex quadratic)

**Scenario.** Running two plants together costs more or less than the sum of their costs: a shared gas pipeline that adds a surcharge when both burn gas, a shared startup crew, a transmission path that both use. The cost becomes Σ cᵢxᵢ + Σ Wᵢⱼxᵢxⱼ with W of mixed sign. Exactly k equal-size units must run.

**Why it is hard for MILP.** A MILP cannot multiply variables. Each product xᵢxⱼ becomes a new variable yᵢⱼ with linear bounds (the McCormick linearization): n(n−1)/2 extra variables and up to n² extra rows. At fractional x the LP can set yᵢⱼ to its most favourable value, so the bound is weak. This is the same reason max-cut and other dense QUBOs are slow as MILPs.

**For QAOA.** This is the native QUBO form: W goes straight into the ZZ couplings, with no extra variables. Of the three families this is the best match for QAOA.

## 3. A fleet of identical units (symmetry)

**Scenario.** Many identical units of a few types (for example rows of identical CTs) must match demand exactly.

**Why it is hard for MILP.** Swapping two identical units gives an equivalent schedule with the same cost. Branch and bound can explore many equivalent subtrees. Ostrowski, Anjos and Vannelli (2015) developed modified orbital branching specifically to remove this symmetry in unit commitment. Modern solvers, HiGHS included, detect some symmetry automatically.

**For QAOA.** Many equivalent optima raise the chance that one shot returns an optimal schedule, so symmetry helps rather than hurts.

## What QAOA work on UC has found

Koretsky et al. (2021, arXiv:2110.12624, IEEE QCE) adapted QAOA to unit commitment with a classical minimizer for the continuous outputs and validated it on small systems in Qiskit simulation. Like our Milestone 4 results, that work demonstrates feasibility, not a speedup over classical solvers.

## How we test

- **Exact simulation (n ≤ 22).** `src/exact_qaoa.py` builds the full 2ⁿ statevector of the same circuit as `src/quantum.qaoa_circuit` (checked against Qiskit's `Statevector` in tests). The result is the **exact** probability p_opt that one shot returns an optimal schedule. TTS99 = ln(0.01) / ln(1 − p_opt) is the number of shots needed for a 99% chance of seeing the optimum.
- **gpu-sv (24–28 qubits): planned, not run.** `experiments.milp_hardness gpu` prepares 6 jobs for qBraid's noise-free GPU statevector simulator. They use angles transferred from 22 qubits, which the `_transfer` rows show work as well as per-instance tuning. We did not submit them. The exact local trend puts the per-shot chance of the optimum at 24–28 plants around 1e-7 to 1e-9, so 10,000 shots would almost surely contain no optimal schedule and would not change the conclusion. `gpu --submit` and `gpu-fetch` are there if someone wants the runs.
- **Baselines.** MILP (HiGHS, B&B nodes and time); random guessing (p_opt = number of optima / 2ⁿ, exact); simulated annealing on the **same QUBO** (1,000 runs × 1,000 sweeps, single-bit flips).
- **Optimum.** Brute force over all 2ⁿ energies, required to equal the MILP optimum on every instance (the run stops otherwise).

## What we found (details: docs/results.md)

- **Market split is genuinely MILP-hard.** Branch-and-bound nodes grow 3–50× per 5 added plants. From 35 plants HiGHS finds no feasible schedule in 30 s. Interaction gets slow because its linearized LP grows with n². Symmetric fleets are solved at the root node up to 50 plants, so modern presolve handles that symmetry.
- **Exact QAOA does not change the scaling.** Up to 22 qubits, QAOA (p = 1–3) beats random guessing by a constant factor, 1.5–4.5×. Its per-shot chance of the optimum still halves with almost every added plant (0.95–0.99 halvings per plant, against 1.00 for random). At 22 plants a 99% chance of seeing the optimum takes millions of shots. The MILP takes a few seconds.
- **The cause is the penalty formulation, not the simulator.** With exact constraints, feasible schedules are rare and separated by penalty barriers. Single-flip SA fails the same way at 22 plants. The next thing to try is a mixer that keeps the constraint satisfied (an XY mixer for "exactly k on"), so QAOA only moves between feasible schedules.

## Honest caveats

- Tuning the QAOA angles uses every bitstring's energy, which already reveals the optimum. Its time is reported separately as classical tuning time. The `_transfer` rows show what you get without per-instance tuning.
- These are single-hour problems, kept small so they fit in an exact simulation. Real UC adds time coupling, which needs n × T qubits.
- SA here uses only single-bit flips on the penalty QUBO, the same move set as the QAOA mixer. A UC-specific heuristic (swap moves that keep the constraint satisfied, or lattice methods for market split) would be much stronger. So SA is a fair same-formulation baseline, not the best classical method.
- MILP times were measured while four experiments shared the CPU. B&B node counts are the robust measure.

## Sources

- G. Cornuéjols, M. Dawande, "A class of hard small 0-1 programs", INFORMS J. Computing 11(2):205–210, 1999. https://pubsonline.informs.org/doi/10.1287/ijoc.11.2.205
- K. Aardal, R. Bixby, C. Hurkens, A. Lenstra, J. Smeltink, "Market split and basis reduction: towards a solution of the Cornuéjols–Dawande instances", INFORMS J. Computing 12(3):192–202, 2000. https://pubsonline.informs.org/doi/10.1287/ijoc.12.3.192.12635
- J. Ostrowski, M. F. Anjos, A. Vannelli, "Modified orbital branching for structured symmetry with an application to unit commitment", Mathematical Programming 150(1):99–129, 2015. https://doi.org/10.1007/s10107-014-0812-y
- S. Koretsky et al., "Adapting Quantum Approximation Optimization Algorithm (QAOA) for Unit Commitment", 2021. https://arxiv.org/abs/2110.12624
- MIPLIB `markshare` instances. https://miplib.zib.de/instance_details_markshare_5_0.html
