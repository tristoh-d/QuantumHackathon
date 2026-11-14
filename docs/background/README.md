# Background: what TVA asked, and reading

TVA (the Tennessee Valley Authority) wrote two problems for this hackathon. This track is the second, unit commitment. This folder holds TVA's problem in its own words and the reading TVA shared. **Follow this track's [README](../README.md) for what to build and submit.** Use this folder to understand your customer: what TVA wants, and why.

| File | What it is |
|---|---|
| This page | TVA's problem, word for word, and what changed for this event |
| | In qBraid Lab, open the two files below from the file browser on the left (their links work on GitHub) |
| [`TVA-Unit-Commitment-and-Economic-Dispatch-Overview.md`](./TVA-Unit-Commitment-and-Economic-Dispatch-Overview.md) | TVA's overview of how utilities decide which plants run and how much each produces (Nov 2). The track README's [Background from TVA](../README.md#background-from-tva) sums it up. Useful for your value story: the cost components, the constraints, and how the decision is made |
| [`TVA-Generic-Data-for-Hackathon.md`](./TVA-Generic-Data-for-Hackathon.md) | TVA's note on which open data to use (Nov 2). It recommends RTS-GMLC, which is where this track's data comes from |

## What TVA asked

> **TVA (G&T): Unit Commitment (UC) with Start/Stop & Ramping**
>
> **Background.** Scheduling thermal and storage units over a day to meet demand and reserve at minimum cost while respecting minimum up/down times, startup costs, and ramp limits. UC is classical-hard (mixed-integer) and a prime candidate for quantum-assisted combinatorial search.
>
> **Challenge (36-hour scope).** Formulate a binary UC for a small time horizon (e.g., 24 hours, 10–20 units). Build a hybrid solver: classical cost evaluation + a quantum subroutine that selects on/off schedules or commit sets under ramp/min-up constraints. Compare against a classical MIP baseline.
>
> **Deliverables**
>
> - Clear UC formulation + code (hybrid workflow).
> - Feasible schedule meeting load & reserve each hour.
> - Objective value vs. classical baseline; constraint violation report.
> - Short write-up on quantum value (speed/quality/robustness).
>
> **Data Needed (ready-to-use sources)**
>
> - RTS-GMLC (CSV + MATPOWER/PLEXOS formats) for generators, costs, time series load/reserve; includes modern fuel mixes, storage and renewables.
> - MATPOWER case files for smaller instances if desired (e.g., case24_ieee_rts).

*From TVA's problem set (Aug 25). TVA's data links are in the track README's [Links](../README.md#links).*

## What's different here

TVA's problem was written for teams with power-systems and quantum experience. Most teams this weekend are new to quantum, have 36 hours, and run on hardware that handles a few dozen two-qubit gates well. So qBraid proposed a simpler version of the problem, and TVA agreed to it (Nov 2). TVA chose not to share TVA-specific data, so the track builds its plants from the public RTS-GMLC test system, as TVA recommended.

| TVA's original | This track |
|---|---|
| 10 to 20 units over 24 hours | 5 plants over 24 hours. 10 plants is a stretch goal |
| Thermal units and storage | Thermal plants. A battery is a stretch goal |
| Startup costs and minimum up/down times | The same, checked classically as you go hour by hour |
| Ramp limits | A stretch goal (`ramps=True` in the MILP; read the caveat about the checker in the track README) |
| Meet load and reserve every hour | The same: demand, plus a 10% reserve |
| A hybrid solver: classical cost evaluation plus a quantum step that picks on/off schedules | The same shape: QAOA proposes each hour's on/off choices, and classical code checks them and keeps the cheapest valid one. Finding out how much the quantum step adds is part of the job (milestone 4) |
| Compared with a classical mixed-integer baseline | The same; the baseline is provided |
| Deliverables: formulation and code, a feasible schedule, cost vs the baseline with a report of broken rules, and a write-up on quantum value | The same, using the checker, in your pitch deck |

Wind and solar (scheduling against net load) is a stretch goal too.
