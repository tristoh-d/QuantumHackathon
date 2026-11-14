# Can a better startup decision at hour 5 lower the day's cost?

Unzip the folder, open StartupDecision.ipynb in qBraid Lab with a Qiskit Python kernel, and choose Run All. The experiment runs locally in the kernel. For a terminal run, install the packages in requirements.txt and run python experiment.py from this folder. The results directory includes the recorded run, per-hour schedules, and 1,000 sampling trials.

## How the experiment works

1. Follow the cheapest feasible single-hour decision through hours 0–4. Keep coal on in hours 5–6 and let eight bits specify the other four plants independently in each hour. Bit 0 is gas at hour 5, followed by peaker A, peaker B, and oil. Bits 4–7 repeat this order at hour 6.
2. For each of the 256 combinations, check demand, spare capacity, and minimum on/off times. From hour 7 onward, complete the day with the same least-cost feasible hourly rule. The rule includes startup costs and dispatch. The organizer's checker verifies the entire day. Optional ramp constraints are disabled throughout, matching the basic track.
3. Give feasible plans an energy from 0 to 1 based on their completed day's cost. Give invalid plans energy 2. One QAOA layer starts with equal weights, applies cost-dependent phases, and mixes the bit strings. A 33 by 33 classical angle search minimizes expected energy on this instance. The resulting Qiskit circuit's exact ideal probabilities are checked against the independent tuning implementation.
4. Draw independent samples with replacement from the ideal distribution. Uniform random sampling uses the same encoding, evaluation and shot budgets. Both may draw invalid plans. Each trial reports the cheapest feasible sample; infinity means it found none. Exactly searching the whole window is an additional classical baseline. The fully informed MILP may change any of the five plants at any hour.
5. Compare whole-day dollars only for valid schedules. The starter cheapest-first cost is included for completeness but its schedule breaks a rule. See results/summary.csv for validation counts. Sample seeds 0–99 vary draws, not forecasts or optimizer training instances.

## Limits and what to test next

The cost layer uses Qiskit's DiagonalGate with a classically enumerated table of completed-day costs. This directly tests whether quantum sampling shifts probability toward useful schedules. Computing the table already identifies the best window plan. This prototype demonstrates neither end-to-end speedup nor savings over exact classical search. A single-layer diagonal gate can compile to many native gates. It is an ideal simulation prototype, not a tuned Forte circuit. For hardware, build a compact approximate cost circuit using the starter QUBO and compare its gate count and solution quality before submitting a job.

The window was chosen from the demand curve. Coal is held on, and the post-window completion rule knows each subsequent hour's forecast when scoring a candidate. The experiment does not test an unknown future or establish savings for TVA. Repeat across additional windows and forecasts before generalizing.

## Sources

Organizers' checker and input data are bundled from qBraid/tn-quantum-hackathon, commit d329c8fcb7ae179ec6c1448b099e94b4a9581ffc, track 3-tva-plant-scheduling. See data/README.md for RTS-GMLC data credit and licensing.

https://github.com/qBraid/tn-quantum-hackathon/tree/d329c8fcb7ae179ec6c1448b099e94b4a9581ffc/3-tva-plant-scheduling
