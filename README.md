# QuantumHackathon: TVA Power Plant Scheduling

This repo is where my team will work on the quantum hackathon project. The track is
[3-tva-plant-scheduling](https://github.com/qBraid/tn-quantum-hackathon/tree/main/3-tva-plant-scheduling):
choose which power plants are on each hour of a day (**unit commitment**) to meet demand + 10% reserve at lowest cost,
using a hybrid of a classical checker and QAOA, then compare it with an exact MILP and run one hour on IonQ hardware.

- **Problem, rules, milestones, judging:** [docs/challenge.md](docs/challenge.md)
- **Code layout and conventions:** [docs/architecture.md](docs/architecture.md)
- **Our numbers (fill in):** [docs/results.md](docs/results.md) · **Deck outline:** [presentation/demo-notes.md](presentation/demo-notes.md)

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest                                              # TODO tests skip until implemented
```

In qBraid Lab, use the **qBraid-SDK (v0.12.2)** kernel and open `notebooks/starter.ipynb`.

## Where the work is (the TODOs)

| TODO | File | Milestone | Test |
|---|---|---|---|
| Hand schedule, 6 hours | `notebooks/starter.ipynb` §1 | 1 | — |
| **TODO 1** cheapest-first rule | [src/classical.py](src/classical.py) `cheapest_first` | 2 | `tests/test_classical.py` |
| **TODO 2** plant cost for one hour | [src/qubo.py](src/qubo.py) `plant_hour_costs` | 3 | `tests/test_qubo.py` |
| **TODO 3** the QUBO matrix | [src/qubo.py](src/qubo.py) `build_qubo` | 3 | `tests/test_qubo.py` |
| Primer: cost layer + optimizer | [src/maxcut.py](src/maxcut.py) | 3 | `tests/test_maxcut.py` |

Everything else (checker, MILP, QAOA, hour-by-hour loop, hardware submission) is provided and works once the TODOs are in.

## Running experiments (from the repo root)

```bash
python -m experiments.benchmark              # MILP vs rule vs QAOA vs random       (milestones 2, 4)
python -m experiments.hour_check             # QUBO "Match!" check, all 24 hours     (milestone 3)
python -m experiments.shots_sweep            # QAOA vs random x shots x seeds        (milestone 4, required)
python -m experiments.hardware_run --dry-run # build circuit + Aer only               (milestone 5)
python -m experiments.hardware_run           # IonQ free simulator, forte-1 noise
```

Add `--fleet 10` for the 10-plant stretch goal. QPU runs need `--device ionq-qpu --i-am-sure` (credits, ≤ 200 shots, send early).

## Layout

```
data/           plants + demand CSVs (RTS-GMLC derived; license in data/README.md)
src/            checker, classical, QUBO, QAOA, loop, hardware, plots, Max-Cut primer
notebooks/      starter + primer notebooks that call src/
experiments/    runnable scripts, one per milestone
tests/          pytest
results/        experiment outputs and hardware job log
docs/           challenge, architecture, results, TVA background
presentation/   deck notes
reference/      untouched copies of the organizers' files
```

Data credit: **DOE/NREL/ALLIANCE, RTS-GMLC**.
