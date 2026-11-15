# Hybrid QAOA + classical look-ahead: results on real TVA days

## Why

Every earlier result came to the same conclusion ([results.md](results.md), Milestone 4 and the TVA sections): the gap to the
MILP comes from the **hour-by-hour loop**, not from the sampler. Each hour keeps the sampled choice that is cheapest
*for that hour*. So it skips a startup that would pay for itself later (GAS_CC at hour 5 on the original day), or it
turns on a plant whose min up time forces expensive hours later. Better sampling cannot fix that.

## What the hybrid does

Same loop as before (`src/scheduler.py`), with one step changed and one optional step added:

1. **Locks** (classical): which plants min up / min down times force on or off.
2. **QUBO + QAOA** (quantum): sample `shots` on/off choices for this hour.
3. **Look-ahead** (classical, new, `src/lookahead.py`): score each valid sampled choice by
   `this hour + the best possible next H hours`. The second term comes from a small MILP: the same formulation as the
   organizers' `solve_milp`, over hours 0 … t+H, with every hour up to t fixed (the schedule so far plus the candidate).
   Fixing the past inside that formulation makes min up / min down times work exactly as in the checker. A
   candidate with no valid way to continue (a dead end) scores ∞. Keep the lowest score.
4. **Shaped QUBO** (optional, `shape_qubo=True`): the QUBO's plant cost c_i, which charges a whole startup to one
   hour, is replaced by the plant's look-ahead value: the best score with the plant on now minus the best score
   with it off (2n small MILPs). A plant that cannot be switched without a dead end becomes a lock. QAOA then puts
   more probability on choices that pay off later. **Random sampling cannot use this information; QAOA can.**

H=0 is the old loop (a test checks that the schedule is identical). "All choices" proposes all 2^n choices
without sampling. It shows the best a given H can do with a perfect proposer.

Code: `src/lookahead.py`, `schedule_day(..., lookahead=H, shape_qubo=..., max_candidates=K, sampler="all")`.
Tests: `tests/test_lookahead.py`.

## 5-plant fleet, 40 real TVA days

Command: `python -m experiments.lookahead run --fleet 5 --shots 20 50 --horizons 4 --all-horizons 1 4 23 --workers 2`
→ `results/lookahead_fleet5.csv` (one row per day × method). Summary: `python -m experiments.lookahead summary --fleet 5`.

These are the same 40 dates as `tva_benchmark quantum`: 5 per season × weekday/weekend, day seed 11, EIA-930 net load.
Each day is scaled so the TVA fleet's 17,735 MW maps to 850 MW. QAOA is p=1 with sampler seed 7. Every day is scored by
the organizers' checker against **its own MILP**.

| Method | H | Shots | Valid days | Gap vs MILP, mean [95% CI] | Median | Days at the optimum | Time per day | Look-ahead MILPs per day |
|---|---|---|---|---|---|---|---|---|
| MILP | — | — | 40 / 40 | 0.00% | 0.00% | 40 | ~0.1 s | — |
| Cheapest-first rule | — | — | 25 / 40 | +5.90% [+3.35, +8.73] | +0.25% | 19 | — | — |
| QAOA, hour by hour | 0 | 20 | 40 / 40 | +10.31% [+8.56, +12.14] | +9.75% | 0 | 0.2 s | 0 |
| Random, hour by hour | 0 | 20 | 33 / 40 | +18.99% [+15.72, +22.72] | +14.85% | 0 | 0.0 s | 0 |
| QAOA + look-ahead | 4 | 20 | 40 / 40 | +9.47% [+7.44, +11.65] | +7.94% | 0 | 4.5 s | 155 |
| **QAOA (shaped QUBO) + look-ahead** | 4 | 20 | 40 / 40 | **+8.16%** [+5.76, +10.63] | +7.15% | 3 | 13.8 s | 409 |
| Random + look-ahead | 4 | 20 | 33 / 40 | +17.39% [+14.33, +20.86] | +12.98% | 0 | 3.8 s | 116 |
| QAOA, hour by hour | 0 | 50 | 40 / 40 | +6.93% [+5.55, +8.40] | +6.83% | 1 | 0.4 s | 0 |
| Random, hour by hour | 0 | 50 | 40 / 40 | +6.23% [+4.81, +7.70] | +5.59% | 1 | 0.1 s | 0 |
| QAOA + look-ahead | 4 | 50 | 40 / 40 | +3.50% [+2.60, +4.55] | +2.79% | 4 | 8.0 s | 230 |
| **QAOA (shaped QUBO) + look-ahead** | 4 | 50 | 40 / 40 | **+3.33%** [+2.30, +4.53] | +2.79% | 11 | 16.4 s | 470 |
| Random + look-ahead | 4 | 50 | 40 / 40 | +4.04% [+3.06, +5.12] | +3.46% | 1 | 7.0 s | 206 |
| All choices + look-ahead | 1 | — | 40 / 40 | +3.67% [+2.64, +4.76] | +3.05% | 11 | 6.9 s | 269 |
| All choices + look-ahead | 4 | — | 40 / 40 | +1.15% [+0.60, +1.83] | +0.00% | 25 | 8.5 s | 265 |
| All choices + look-ahead | 23 | — | 40 / 40 | +0.00% | +0.00% | 40 | 13.2 s | 268 |

(95% CI: bootstrap of the mean over days, 2,000 resamples. "Days at the optimum": gap < 0.01%. Times are with 2 days
running in parallel. The MILP time is from the earlier TVA runs.)

Paired, same day (negative = first is cheaper):

| Comparison | Shots | Days valid for both | First cheaper / tie / second cheaper | Mean difference |
|---|---|---|---|---|
| QAOA + look-ahead vs QAOA hour by hour | 20 | 40 | 23 / 11 / 6 | −0.84 points |
| QAOA + look-ahead vs QAOA hour by hour | 50 | 40 | **33 / 7 / 0** | **−3.44 points** |
| Shaped vs plain QUBO (both + look-ahead) | 20 | 40 | 26 / 6 / 8 | −1.32 points |
| Shaped vs plain QUBO (both + look-ahead) | 50 | 40 | 17 / 18 / 5 | −0.16 points |
| QAOA (shaped) vs random, both + look-ahead | 20 | 33 | **29 / 0 / 4** | **−7.65 points** |
| QAOA (shaped) vs random, both + look-ahead | 50 | 40 | 27 / 4 / 9 | −0.71 points |
| QAOA (plain) vs random, both + look-ahead | 50 | 40 | 18 / 7 / 15 | −0.54 points |

### What this shows

- **The look-ahead halves the gap.** At 50 shots, QAOA hour by hour is +6.93% above the MILP. With a 4-hour look-ahead it
  is +3.50% (+3.33% with the shaped QUBO), cheaper on 33 of 40 days and never more expensive. This is also below the
  cheapest-first rule (+5.90%, which breaks min up / min down times on 15 of 40 days). Every hybrid day is valid.
- **The look-ahead closes the gap when it is given the right choices.** With all 32 choices proposed, the gap is +3.67%
  at H=1 and +1.15% at H=4 (25 of 40 days exactly optimal). At H=23 it is 0.00% on all 40 days. The look-ahead step
  is sound; what limits the hybrid is whether the sampler proposes the choice the look-ahead wants.
- **That is where QAOA matters.** The proposer is the bottleneck, and QAOA proposes better choices than random,
  most clearly at low shot counts. At 20 shots, QAOA (shaped) + look-ahead is 7.65 points cheaper than random +
  look-ahead on the same days (cheaper on 29 of 33), and valid on 40 / 40 days vs 33 / 40. At 50 shots, random
  already sees most of the 32 choices and the advantage shrinks to 0.5–0.7 points (QAOA cheaper on 27, random on 9).
- **The shaped QUBO helps most when shots are scarce.** At 20 shots it is 1.32 points cheaper than the plain QUBO
  (cheaper on 26 of 40 days). It reaches the exact optimum on 11 days at 50 shots, against 4 for the plain QUBO and
  1 for random. The plain QUBO charges GAS_CC's full $27,650 startup to one hour, so QAOA rarely proposes that
  startup. The shaped QUBO spreads the cost over the hours the plant will run. On the original 5-plant day, this
  raised QAOA's probability on the look-ahead's best choice from 0.036 to 0.126 at hours 14–15.
- **Remaining gap at 50 shots (+3.3%) vs the "all choices, H=4" ceiling (+1.15%).** About 2 points are lost because
  50 p=1 shots still miss the right choice in some hours. More shots, p=2, or a longer H would reduce this
  (see the 10-plant probe below for the cost of more candidates).

### Honest accounting

- **The classical work grows.** The 4-hour look-ahead solves 150–470 small MILPs per day, 4–16 s per day, against
  ~0.1 s for the one full-day MILP. "All choices + H=23" is the MILP answer obtained the slow way. The point of the
  hybrid is not speed on this problem size: at 5–10 plants the MILP is fast and exact
  ([milp_hard_cases.md](milp_hard_cases.md)). The point is that **QAOA's job becomes the right one**: proposing a short
  list of promising choices per hour, while a short-horizon classical solver checks them against the future.
- **The quantum gain is a sample-efficiency gain**, the same kind as in Milestone 4: QAOA's candidates are better per
  shot, and the gap between QAOA and random is largest at the lowest shot count. On 5 plants, 50 random shots
  already cover most of the 32 choices.
- **Not comparable one-to-one with older tables.** During this work the scheduler gained qubit reduction (locked
  plants and unusable slack bits are removed before QAOA runs; `reduce=True` is now the default, for both QAOA and
  random). This is why "QAOA, hour by hour, 20 shots" is valid on 40 / 40 days here, against 19 / 40 in
  [results.md](results.md). Within this file, every row uses the same code.

## 10-plant fleet: one-day probe

This fleet is not yet run over the 40 days. One spring-weekend TVA day was scaled to the 10-plant fleet (1,500 MW, 13 qubits,
1,024 choices per hour), with 1000 shots and H=4. It was run **before** qubit reduction was added:

| Method | Gap vs MILP | Time | Look-ahead MILPs |
|---|---|---|---|
| QAOA, hour by hour | +13.37% | 15 s | 0 |
| QAOA + look-ahead | +12.14% | 178 s | 8,339 |
| QAOA (shaped QUBO) + look-ahead | +12.97% | 392 s | 7,891 |
| Random + look-ahead | +7.21% | 530 s | 7,528 |
| All choices + look-ahead | **+0.05%** | 1,002 s | 12,133 |

On 10 plants the look-ahead still reaches the optimum when it sees every choice (+0.05%). On this one day,
random + look-ahead (+7.21%) beat QAOA + look-ahead (+12–13%). The likely reason is that QAOA's 1000 shots concentrate on
fewer distinct choices, while random spreads over more of the 1,024. One day is not enough to conclude. Scoring every
unique sample also costs ~8,000 MILPs per day. The planned 40-day run caps the look-ahead at the 32 choices sampled
most often (`--max-candidates 32`), where QAOA's ranking matters and random's does not:

```
python -m experiments.lookahead run --fleet 10 --shots 200 1000 --horizons 4 --all-horizons 4 --max-candidates 32 --workers 2
```

## The 20-plant TVA fleet

Not run with QAOA. That fleet needs 25 qubits, beyond the local simulator (`MAX_LOCAL_QUBITS = 20`), as in the earlier
TVA results. The look-ahead itself would work there unchanged (it is the MILP formulation).
