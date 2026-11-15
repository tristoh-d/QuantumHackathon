# QPE / HHL approach: results

An alternate quantum approach to the unit-commitment problem, built on quantum phase estimation (QPE). It follows Stein et al., *Exponential Quantum Speedup for Simulation-Based Optimization Applications*, [arXiv:2305.08482](https://arxiv.org/abs/2305.08482) (here "the paper"), and uses QPE in two of the three ways the blueprint lists:

1. **Network equations by HHL.** HHL solves the DC power flow B̄θ = p̄ for the grid. QPE writes the eigenvalues of B̄ into a clock register.
2. **Cost readout by amplitude estimation.** Amplitude estimation is QPE on a Grover operator. It writes the transmission cost of each on/off choice into a register, coherently. A phase layer turns that register into the QAOA cost phase (paper Thm. 10).

Item 3 of the blueprint (QPE + Grover minimum finding) is not built. Item 2 is used here only for the cost readout, not for expected cost over demand scenarios.

**Bottom line:**

- **Every quantum piece works on an ideal simulator and matches the exact classical answer.**
  - HHL fidelity is 0.99998.
  - The A-B flow comes out within 1.6% for every hour.
  - With a 10-bit register, the transmission-cost readout is within 1% of exact.
  - The QuSO cost layer applies the right phase to within 1%.
- **It is not more efficient than the MILP at any grid size we can measure, and not at any realistic size by extrapolation.**
  - The readout alone needs 1,023 Grover calls (2,047 HHL calls) per circuit.
  - The paper's speedup needs the condition number κ of B̄ to stay bounded. On real-shaped grids, κ grows at least linearly with the number of buses.
  - We found that the paper's Lem. 19, which promises a bounded κ on expander grids, has an inequality in the wrong direction. Details are in [the condition-number section](#the-condition-number-does-not-stay-bounded).

## The problem

| | |
|---|---|
| Fleet | 5 plants (`data/plants.csv`), 24 hours (`data/demand.csv`), same rules and checker as the main track |
| Grid | 3-area equivalent of RTS-GMLC, built from its real tie lines (`data/network_rts3.csv`, see `data/README.md`) |
| Plants | Area A: COAL, GAS_CC, PEAKER_A, OIL. Area B: PEAKER_B. The whole load sits in area C (the demand curve is RTS region 3 load) |
| Cost | Generation cost (startup + no-load + energy, as in the checker) **+ transmission cost** $2/MWh × \|flow\| on each tie line (paper Def. 7 plus Rem. 13) |
| Line limits | Real RTS ratings (500-1,175 MW), checked and reported, not enforced. No schedule in this document overloads a line |
| Classical baseline | **Network MILP** (`src/network_milp.py`): the organizers' MILP plus DC power-flow transfer factors and \|flow\| terms. It is exact for this cost |

B̄ is 2 × 2 (area C is the reference), with eigenvalues 9.96 and 76.08, so κ = 7.64.

## The method

```
QAOA, p = 1, on the 8 qubits of the existing QUBO (5 plants + 3 slack)

  |+>^8 ─ e^{-i γ E_gen(z)} ─ QSim ─ P(γ) ─ QSim† ─ RX(2β)^8 ─ measure
          (existing QUBO)     └── transmission-cost unitary (paper Thm. 10) ──┘

QSim |x>|0> = |x>|y(x)>, on 5 plant qubits + flag + sys + 4 clock + anc + m readout qubits:
  1. load p̄_x / N with a flag qubit       uniformly controlled RY on the plant qubits (N = max |p̄_x|, fixed)
  2. HHL: QPE(e^{iB̄t}) → RY(2 arcsin(C/λ)) → QPE†    ancilla amplitude C B̄⁻¹ p̄_x / N
  3. H on the system qubit                  its |1> amplitude ∝ θ_A - θ_B, which is the flow on line A-B
  4. amplitude estimation (QPE on the Grover operator Q = -A S₀ A† S_good)
     good = (anc=1, flag=0, sys=1, clock=0),  a(x) = C² ρ_AB² / (2 N² b_AB²)  →  y with sin²(πy/2^m) ≈ a(x)
P(γ): diagonal phase γ K sin(πy/2^m) on the readout register, the same for every x (no cost table is loaded)
```

- **Why only line A-B.** Flows into the reference area C are never negative here, and ρ_AC + ρ_BC equals total generation, which equals demand for every valid choice. So that part of the transmission cost is the same for every valid choice in an hour, a global phase. Only c_AB |ρ_AB| needs the linear solve.
- **Scaling HHL without solving first.** The evolution time comes from the Gershgorin bound λ_max ≤ 2 d_max (paper Cor. 6). C is the smallest eigenvalue the clock can represent. Recovering the norm uses paper Rem. 7: |θ| = |p̄| √P(success) / C.
- **Exact simulation.** The plant qubits only control QSim. So the coherent circuit on |x⟩ is a fixed unitary per choice, and we simulate it per choice in the Grover operator's eigenbasis (`QSimMatrices`). Two tests check that this gives the gate-level circuit's output to 1e-8, both coherent in x and for a fixed choice.
- **Hour-by-hour loop** (`quso_day`). Same as the existing scheduler: tune (γ, β), draw 200 samples, and keep the cheapest valid sampled choice. The difference is that "cheapest" now includes the transmission cost.

Code: `src/network.py` (grid, DC power flow), `src/hhl.py`, `src/quso.py` (QSim, cost layer, QuSO-QAOA, day loop), `src/network_milp.py`. Experiments: `python -m experiments.quso_uc {components,day,scaling,qbraid}`.

## Tests

`pytest tests/test_quso.py`: 26 tests, all passing. Each one checks a quantum piece against the exact classical answer it must reproduce.

| What is checked | Expected output | Test |
|---|---|---|
| Grid is the RTS 3-area equivalent | Laplacian rows sum to 0; B̄ invertible; κ = 7.64; b_AB = 1/0.161 + 1/0.075 + 1/0.074 | `test_grid_is_the_rts_three_area_equivalent` |
| Plants are in their RTS areas | A, A, A, B, A | `test_plants_sit_in_their_rts_areas` |
| Power is conserved | ρ_AC + ρ_BC = generation in A and B, all 32 choices | `test_power_flow_conserves_power` |
| Hand example: 100 MW from A to C | ρ_AC + ρ_BC = 100; ρ_AB = ρ_BC; 0 < ρ_AB < ρ_AC | `test_power_flow_hand_example` |
| HHL solves the DC power flow | fidelity > 0.9999, norm error < 3% (4 right-hand sides) | `test_hhl_solves_dc_power_flow` |
| HHL gets the A-B flow | within 2% for the valid choices | `test_hhl_flow_difference_is_accurate` |
| Gershgorin bound | ≥ true λ_max | `test_gershgorin_bound_is_an_upper_bound` |
| Injection loading | RY angles give exactly p̄/N on the qubits | `test_prep_angles_load_the_injections` |
| a(x) encodes the flow | inverting a(x) gives \|ρ_AB\| | `test_good_probability_encodes_the_ab_flow` |
| Fast simulator = circuit (one choice) | same readout distribution, to 1e-8 | `test_gate_level_qae_matches_matrix_simulation_for_one_choice` |
| Fast simulator = circuit (coherent in x) | same readout distribution, to 1e-8 | `test_coherent_qae_matches_per_choice_simulation` |
| Readout with m = 10 | \|ρ_AB\| within 3% | `test_qae_reads_the_ab_flow_with_10_bits` |
| Readout with m = 4 | reads 0 (too coarse) | `test_qae_is_too_coarse_with_few_bits` |
| Readout error | within the Brassard et al. bound | `test_qae_error_within_brassard_bound` |
| Cost layer (paper Thm. 10) | phase = −γ c_AB \|ρ_AB\| within 0.05 rad; returns to \|0⟩ with amplitude > 0.95 | `test_cost_layer_applies_the_transmission_phase` |
| Cost layer at zero phase | identity | `test_cost_layer_is_identity_at_zero_phase` |
| QuSO-QAOA output | sums to 1; uniform at γ = 0 | `test_quso_probabilities_are_a_distribution` |
| QuSO vs plain QAOA at $2/MWh | max difference < 1e-4 | `test_quso_matches_plain_qaoa_when_qsim_is_off_or_phase_is_tiny` |
| QuSO day loop | valid schedule (3-hour run) | `test_quso_day_gives_a_valid_schedule_for_a_few_hours` |
| κ of the reduced Laplacian | λ_min ≤ 3/(N−1) < λ₂; κ grows > 10× for 16× more buses; κ > the Lem. 21 bound at N = 2,048 | `test_grounded_laplacian_condition_number_grows_with_grid_size` |
| Network MILP, lines free | equals the organizers' MILP | `test_network_milp_with_free_lines_is_the_organizers_milp` |
| Network MILP is a lower bound | ≤ the total cost of any schedule; ≥ the network-blind MILP | `test_network_milp_is_a_lower_bound` |

## Results 1: the quantum pieces (ideal simulator)

`python -m experiments.quso_uc components` → `results/quso_components.json`.

**HHL** (4 clock qubits, 6 qubits, 68 CX), on every hour of the network MILP's schedule: fidelity ≥ 0.99998, A-B flow error +1.6%, success probability 0.126.

**Amplitude-estimation readout** of |ρ_AB| at hour 14. The two valid choices differ by 17 MW of A-B flow, which is $35/h:

| Readout bits m | Grover calls | HHL calls | COAL+GAS_CC (exact 292 MW) | + PEAKER_B (exact 275 MW) | Tells them apart? |
|---|---|---|---|---|---|
| 4 | 15 | 31 | 0 MW | 0 MW | no |
| 6 | 63 | 127 | 314 MW | 314 MW | no |
| 8 | 255 | 511 | 314 MW | 314 MW | no |
| **10** | **1,023** | **2,047** | **294 MW** | **275 MW** | **yes** |
| 12 | 4,095 | 8,191 | 299 MW | 280 MW | yes |

The amplitude is small (a ≈ 0.002), because ρ_AB lies along B̄'s stiff eigenvector (λ = 76). The readout error falls only as 1/2^m, the O(1/ε) cost of amplitude estimation. At m = 12 the readout settles near HHL's own +1.6% bias, not the exact flow.

**Cost layer** (m = 10, γ = 10⁻³): phase −0.590 rad vs exact −0.585 rad (COAL+GAS_CC), and −0.555 vs −0.550 (+ PEAKER_B). The state returns to |0⟩ with amplitude 0.998 and 0.995.

**Circuit size** (transpiled to CX + one-qubit gates; controlled-Q controls only the two reflections):

| m | One choice: qubits / CX | Coherent in x (inside QAOA): qubits / CX | HHL calls |
|---|---|---|---|
| 2 | 9 / 1,501 | 14 / 1,393 | 7 |
| 3 | 10 / 3,409 | 15 / 3,029 | 15 |
| 6 | 13 / 30,095 | 18 / 25,907 | 127 |
| 10 | 17 / 487,121 | 22 / 417,653 | 2,047 |

These counts transpile each block on its own, so they are an upper bound. Transpiling the whole m = 2-3 circuit at once (as sent to qBraid below) gives 811-1,803 CX.

One QuSO-QAOA circuit at m = 10 uses QSim and QSim†: about 835,000 CX, against 56 CX for the plain QAOA circuit used in Milestone 5.

## Results 2: the whole day (ideal simulator)

`python -m experiments.quso_uc day --m 10` → `results/quso_day_m10.json` (seed 7, 200 shots per hour, p = 1). Every schedule is scored the same way: the checker's generation cost (merit-order dispatch) plus $2/MWh × |flow| on each tie line.

| Method | Valid | Generation | Transmission | **Total** | Gap vs network MILP | Wall-clock |
|---|---|---|---|---|---|---|
| **Network MILP** (optimum) | yes | $327,924 | $32,707 | **$360,632** | 0 | 0.45 s (1 B&B node) |
| MILP, network-blind (organizers') | yes | $327,924 | $32,707 | $360,632 | 0.00% | 0.33 s |
| QAOA, existing, network-blind pick | yes | $351,082 | $32,603 | $383,685 | +6.39% | 15 s |
| Random sampling | yes | $351,082 | $32,603 | $383,685 | +6.39% | 0.6 s |
| QAOA, network-aware pick (control, no QSim) | yes | $351,082 | $32,603 | $383,685 | +6.39% | 347 s |
| **QuSO** (HHL + amplitude estimation, m = 10) | yes | $351,082 | $32,603 | **$383,685** | **+6.39%** | 813 s (simulator) |

- **QuSO gives the same schedule as plain QAOA, hour for hour.** The transmission phase is about 10⁻⁴ of the QUBO's energy range, so it changes the probabilities by under 10⁻⁴ (a test checks this). The valid choice it would favor (PEAKER_B on, $35/h less line cost) costs far more in startup and no-load.
- **The network MILP keeps the network-blind MILP's schedule.** At $2/MWh the network does not change the optimal commitment. It adds $32,707 (9%) that every method pays almost equally.
- **The +6.39% gap belongs to the hour-by-hour loop, not the sampler.** Random sampling with the same loop gets the same day. This is the short-sightedness already described in `docs/results.md` (Milestone 4).
- **No schedule overloads a tie line.**
- **Work per day:**
  - QuSO used 19.7 million HHL calls to sample (24 hours × 200 shots × 4,094 HHL calls per circuit).
  - Its 907 tuning evaluations would cost another 743 million on a real device, where each evaluation needs 200 circuits.
  - Brute force needs 768 classical power-flow solves for the day.
  - The network MILP needs none per choice: one root LP for the whole day.

## Results 3: on qBraid (IonQ simulator, ideal and forte-1 noise)

`python -m experiments.quso_uc qbraid` → `results/quso_qbraid.json`. Every job is also logged in `results/hardware_runs.csv`, with counts in `results/counts/`. Setup:
- Hour 14, the two valid choices, 1,000 shots per job.
- Circuits transpiled to CX + one-qubit gates before submission.
- Free IonQ cloud simulator. "forte-1" is its Forte noise model.

The coherent m = 10 QSim (22 qubits, about 418,000 CX) is too large to send, so we sent its building blocks for one choice at a time:

| Circuit | What it estimates | Qubits | CX |
|---|---|---|---|
| HHL | θ = B̄⁻¹p̄, then the A-B flow from the post-selected system qubit and Rem. 7 | 6 | 68 |
| A operator, measured | a(x) by plain sampling (classical Monte Carlo readout, error about 1/√shots) | 7 | 68-70 |
| Amplitude estimation, m = 2 and 3 | a(x) by QPE on the Grover operator | 9-10 | 811-1,803 |

TVD is the total variation distance between the measured distribution and the exact statevector (0 = identical, 1 = nothing in common).

| Choice (exact \|ρ_AB\|) | Circuit | Ideal: TVD | Ideal: \|ρ_AB\| read | forte-1: TVD | forte-1: \|ρ_AB\| read |
|---|---|---|---|---|---|
| COAL+GAS_CC (292 MW) | HHL | 0.003 | 288 MW | 0.375 | 335 MW |
| | A, sampled | 0.003 | 286 MW | 0.365 | 858 MW |
| | QAE m = 2 (811 CX) | 0.003 | 0 MW (y = 0) | 0.983 | 4,522 MW |
| | QAE m = 3 (1,753 CX) | 0.006 | 0 MW (y = 0) | 0.990 | 5,909 MW |
| + PEAKER_B (275 MW) | HHL | 0.003 | 291 MW | 0.359 | 185 MW |
| | A, sampled | 0.003 | 286 MW | 0.365 | 1,070 MW |
| | QAE m = 2 (831 CX) | 0.006 | 0 MW (y = 0) | 0.980 | 6,396 MW |
| | QAE m = 3 (1,803 CX) | 0.017 | 0 MW (y = 0) | 0.979 | 4,522 MW |

- **Ideal: the circuits run correctly on a remote backend.** Every distribution matches the exact statevector (TVD ≤ 0.017). HHL reads the flow within 1-6%.
- **Ideal amplitude estimation reads 0 at m = 2-3,** exactly as the local simulator predicts (`test_qae_is_too_coarse_with_few_bits`). These register sizes cannot resolve a ≈ 0.002.
- **Plain sampling of a is also too coarse.** a ≈ 0.002 is 2 good shots out of 1,000, so both choices read 286 MW. Telling them apart by sampling would take about 10⁶ shots (error ∝ 1/√shots). Amplitude estimation's error ∝ 1/2^m is the point of using QPE, but it only pays off at m ≈ 10.
- **With Forte noise, the 68-CX circuits keep a little signal and the amplitude-estimation circuits keep none.**
  - HHL is off by 15-33%.
  - Noise inflates the good-state probability tenfold (0.018-0.028 vs 0.002), so the sampled readout gives 858-1,070 MW.
  - The 811-1,803 CX amplitude-estimation circuits are fully scrambled (TVD 0.98-0.99).
  - The real readout needs about 418,000 CX, which is far beyond any noisy device.

Job IDs (all `ionq:ionq:sim:simulator-a99b-qjob-…`):

| Choice | Circuit | Ideal | forte-1 |
|---|---|---|---|
| 3 | HHL | `6af9122fc8f5265fb3f22960` | `6af9124fc8f5265fb3f2297b` |
| 3 | A, sampled | `6af91272c8f5265fb3f2299c` | `6af91293c8f5265fb3f229bb` |
| 3 | QAE m = 2 | `6af91309c8f5265fb3f22a1b` | `6af9136bc8f5265fb3f22a72` |
| 3 | QAE m = 3 | `6af913f5c8f5265fb3f22ad6` | `6af9147fc8f5265fb3f22b40` |
| 11 | HHL | `6af914c8c8f5265fb3f22baf` | `6af914dbc8f5265fb3f22bbb` |
| 11 | A, sampled | `6af914eec8f5265fb3f22bcc` | `6af914fdc8f5265fb3f22bdd` |
| 11 | QAE m = 2 | `6af9152cc8f5265fb3f22bf7` | `6af91565c8f5265fb3f22c2d` |
| 11 | QAE m = 3 | `6af915ddc8f5265fb3f22c81` | `6af91668c8f5265fb3f22d0b` |

## Results 4: efficiency (oracle calls and how they scale)

As agreed, "more efficient than the MILP" is measured in **oracle calls and resources**, not wall-clock time. One oracle call is one DC power-flow solve: an HHL call on the quantum side, a sparse LU solve on the classical side.

### At our size (3 buses, one hour)

| Method | Power-flow solves per hour | Other work |
|---|---|---|
| Classical brute force | 32 (one per on/off choice) | 32 dispatches |
| Network MILP | 0 per choice. One 2 × 2 inverse for the transfer factors, once for the whole day | LP relaxation solved at the root (1 B&B node) for all 24 hours in about 0.1 s |
| QuSO (m = 10, 200 shots, p = 1) | **200 × 2 × 2,047 = 818,800 HHL calls** to sample, plus the same again for each tuning evaluation on a real device | 835,000 CX per circuit |

### Growing the grid

`python -m experiments.quso_uc scaling` → `results/quso_scaling.csv`. The same 5 plants and 24 hours sit on synthetic grids of 16 to 1,024 buses with RTS-like susceptances (5-35 pu) and the load spread over all buses. There are two grid shapes: random 3-regular graphs (expanders, the paper's best case) and square lattices (closer to real grids).

- **Classical:** we time one sparse power-flow solve and the full-day network MILP.
- **Quantum:** we count HHL calls per hour (200 shots × 2 × 2,047) times CX per HHL call from the paper's Rem. 8 cost, log₂N · s · κ · log(κs/ε) with ε = 0.01. The constant is calibrated to our measured 68-CX HHL at 3 buses. This side is a model, not a measurement.

| Grid | N | κ(B̄) | One classical solve | Network MILP, whole day | Quantum CX per day (model) |
|---|---|---|---|---|---|
| expander | 16 | 75 | 0.54 ms | 0.50 s | 9.4 × 10¹⁰ |
| expander | 64 | 379 | 0.51 ms | 1.27 s | 8.2 × 10¹¹ |
| expander | 256 | 1,895 | 2.6 ms | 17.1 s | 6.2 × 10¹² |
| expander | 1,024 | 5,971 | 31 ms | 67.6 s | 2.6 × 10¹³ |
| lattice | 16 | 70 | 0.09 ms | 0.21 s | 1.1 × 10¹¹ |
| lattice | 64 | 808 | 0.14 ms | 1.37 s | 2.4 × 10¹² |
| lattice | 256 | 4,575 | 0.53 ms | 1.77 s | 2.0 × 10¹³ |
| lattice | 1,024 | 23,085 | 2.9 ms | 18.1 s | 1.4 × 10¹⁴ |

Fitted growth with grid size N:

| | Expander | Lattice |
|---|---|---|
| κ(B̄) | N^1.09 | N^1.35 |
| One classical solve | N^1.05 | N^0.89 |
| Network MILP, whole day | N^1.25 | N^1.19 |
| **Quantum, whole day** | **N^1.39** | **N^1.66** |

**With the measured κ, the quantum cost grows faster than the MILP's, so there is no crossover.** At 100 ns per CX (fast superconducting, sequential) the quantum day takes 2 × 10⁴ to 1 × 10⁶ times longer than the MILP across this range. At Forte-class speed (about 600 µs per two-qubit gate) it takes 10⁸ to 10¹⁰ times longer.

**Even in the paper's best case** (κ frozen at its 16-bus value, so the quantum cost grows only as log N), the quantum day overtakes the N^1.25 MILP only at about:

| CX time | Crossover grid size |
|---|---|
| 100 ns | 1.7 × 10⁵ buses |
| 1 µs | 1.2 × 10⁶ buses |
| 600 µs | 2.6 × 10⁸ buses |

For comparison, the whole US Eastern Interconnection model has about 70,000 buses. These crossovers also assume error-free qubits, an extrapolated MILP trend, and that reading the answer needs no more than 200 shots.

### The condition number does not stay bounded

The paper's exponential speedup for this problem (Lem. 21) rests on κ(B̄) staying bounded on expander grids. Lem. 19 chains d_min ϕ²/2 ≤ d_min ν₂ ≤ λ₂ ≤ λ_min(B̄), with the last step "by Cauchy interlacing". Our numbers say otherwise:

| N (random 3-regular, unit weights) | 16 | 64 | 256 | 1,024 |
|---|---|---|---|---|
| Fiedler value λ₂(L) | 0.431 | 0.246 | 0.190 | 0.176 |
| λ_min(B̄) | 0.100 | 0.026 | 0.0061 | 0.0014 |
| 3/(N−1) (Rayleigh bound below) | 0.200 | 0.048 | 0.0118 | 0.0029 |
| κ(B̄) | 58 | 223 | 964 | 4,056 |

- **Why it cannot be bounded.** Take x = all ones on the non-reference buses. Then xᵀB̄x / xᵀx = (weight of the reference bus's lines) / (N−1). So λ_min(B̄) ≤ d_ref/(N−1) for every grid, and κ grows at least linearly in N.
- **The interlacing goes the other way.** Cauchy interlacing gives λ₁(L) = 0 ≤ λ_min(B̄) ≤ λ₂(L), so λ_min ≤ λ₂, not ≥.
- **The bound breaks in practice.** At N = 2,048, κ passes the constant bound Lem. 21 gives for d = 3 (4 / (½ − √2/3)² ≈ 4,892). `test_grounded_laplacian_condition_number_grows_with_grid_size` checks all three statements.

This doesn't affect the paper's general framework. It does mean the "constant κ, so exponential speedup" claim for this power-flow formulation does not hold as stated, and HHL's cost here grows at least as N log N.

## What this means

- **The QPE approach is a working, testable construction, not a faster one.** HHL, amplitude estimation and the paper's QuSO cost unitary all reproduce the exact answers on an ideal simulator, and 26 tests pin them down.
- **At $2/MWh the network barely moves the decision.** Transmission is about 9% of the day's cost, but almost all of it (power into area C) is the same for every valid choice. Only about $35/h of loop flow on line A-B depends on the choice, and the network MILP's schedule is the same as the network-blind MILP's.
- **The readout is the expensive part.** Telling a 17 MW difference apart takes 1,023 Grover calls. That is the O(1/ε) price of amplitude estimation, and it multiplies every HHL call.
- **The speedup argument needs bounded κ, and real grids do not give it.** Even granting the paper's best case, the crossover with a classical MILP is at 10⁵ to 10⁸ buses on error-free hardware.

## Limits

- **Grid size.** The 3-area grid is small enough that B̄ is 2 × 2. Larger grids enter only through the resource model (the quantum side of the scaling table is not simulated).
- **HHL variant.** We use QPE-based HHL, not the paper's QSVT solver. With a dense 2 × 2 B̄, the controlled e^{iB̄t} gates are exact one-qubit unitaries; the model constant is calibrated on this circuit.
- **Readout shortcut.** QSim reads only |ρ_AB|, using the facts that flows into C are never negative and sum to generation. The paper's general readout ⟨c, |B′Πθ|⟩ needs a block-encoding of B′ and costs more.
- **Tuning.** Angles are tuned on the exact simulator. On a device, every tuning evaluation would cost another 200 circuits.
- **Network effect.** With $2/MWh the network effect is small by construction (`data/README.md` explains the price). A higher price changes the MILP's schedule only at around $50/MWh.
