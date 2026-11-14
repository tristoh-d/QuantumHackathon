"""TVA plant scheduling (unit commitment): hybrid classical + QAOA solver.

Module map (see docs/architecture.md):
    check       organizers' checker + MILP baseline (read-only)
    config      constants, fleets, Problem loader
    classical   cheapest-first rule (TODO 1) + MILP wrapper
    qubo        one hour as a QUBO (TODO 2, TODO 3) + brute-force helpers
    quantum     QUBO -> Ising, QAOA circuit, angle tuning (needs qiskit)
    scheduler   the hour-by-hour loop (QAOA or random sampler)
    hardware    building, running and logging the hardware circuit
    plotting    charts used by the notebooks and experiments
    maxcut      the QAOA primer (Max-Cut, two TODOs)
"""
