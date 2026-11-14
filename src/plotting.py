"""Charts from the starter notebook, as reusable functions. Each returns the matplotlib Axes/Figure."""
import matplotlib.pyplot as plt
import numpy as np

from src.config import COLORS, Problem
from src.qubo import label


def plot_demand(problem: Problem, ax=None):
    """Demand and demand + reserve across the day, with the COAL / COAL+GAS_CC capacity lines."""
    if ax is None:
        ax = plt.subplots(figsize=(8, 3.5))[1]
    h = problem.hours
    ax.step(h, problem.demand, where="mid", color=COLORS["milp"], lw=2, label="demand")
    ax.step(h, problem.demand + problem.reserve, where="mid", color=COLORS["qaoa"], lw=2, ls="--",
            label="demand + reserve (10%)")
    if problem.fleet == "5":
        for level, text, x in [(350, "COAL alone", 8), (700, "COAL + GAS_CC", 0)]:
            ax.axhline(level, color="gray", lw=0.8)
            ax.text(x, level + 8, text, color="dimgray", fontsize=8)
    top = max(problem.demand + problem.reserve) * 1.25
    ax.set(xlabel="hour", ylabel="MW", title="Tomorrow's demand", ylim=(0, top))
    ax.legend(loc="lower right")
    return ax


def plot_schedule(schedule, names, title, ax=None):
    """Green = on. One row per plant, one column per hour."""
    schedule = np.asarray(schedule)
    if ax is None:
        ax = plt.subplots(figsize=(8, 0.45 * len(names) + 1))[1]
    ax.imshow(schedule.T, aspect="auto", cmap="Greens", vmin=0, vmax=1.4)
    ax.set_yticks(range(len(names)), names)
    ax.set_xticks(range(0, schedule.shape[0], 2))
    ax.set_xlabel("hour")
    ax.set_title(title)
    return ax


def plot_choice_probs(pc, names, best_k, is_valid, title, top_n=8, ax=None):
    """Bar chart of the most likely on/off choices (orange = best), against a 1/2^n random guess."""
    if ax is None:
        ax = plt.subplots(figsize=(8, 3.2))[1]
    top = np.argsort(-pc)[:top_n]
    ax.bar(range(len(top)), pc[top], color=[COLORS["qaoa"] if k == best_k else COLORS["milp"] for k in top])
    ax.axhline(1 / len(pc), color="gray", ls="--", lw=1, label=f"random guess (1/{len(pc)})")
    ax.set_xticks(range(len(top)), [label(int(k), names) + ("" if is_valid[k] else "\n(not valid)") for k in top],
                  rotation=35, ha="right", fontsize=8)
    ax.set(ylabel="probability", title=title)
    ax.legend()
    return ax


def plot_comparison(results: dict, qaoa_log=None, random_log=None):
    """results: {method name: (check_schedule result, color)}. Left: gap vs MILP. Right: sample quality."""
    fig, axes = plt.subplots(1, 2, figsize=(12, 3.4))
    gaps = [r["gap_pct"] or 0.0 for r, _ in results.values()]
    axes[0].barh(list(results), gaps, color=[color for _, color in results.values()])
    for y, (r, _) in enumerate(results.values()):
        broken = f", {len(r['violations'])} rule(s) broken" if r["violations"] else ""
        axes[0].text(max(r["gap_pct"] or 0.0, 0) + 0.1, y, f"{(r['gap_pct'] or 0.0):+.2f}%{broken}",
                     va="center", fontsize=8)
    axes[0].invert_yaxis()
    axes[0].set_xlim(0, 1.4 * max(max(gaps), 1))
    axes[0].set(xlabel="gap vs MILP optimum (%)", title="Daily cost")
    if qaoa_log is not None:
        hours = [row["hour"] for row in qaoa_log]
        axes[1].plot(hours, [row["p_best"] for row in qaoa_log], "o-", color=COLORS["qaoa"], ms=4,
                     label="QAOA: chance of the best choice")
        axes[1].plot(hours, [row["valid_share"] for row in qaoa_log], "s-", color=COLORS["rule"], ms=4,
                     label="QAOA: share of valid samples")
        n_choices = 2 ** len(qaoa_log[0]["pick"])
        axes[1].axhline(1 / n_choices, color=COLORS["random"], ls=":", label="random: chance of the best choice")
    if random_log is not None:
        axes[1].plot([row["hour"] for row in random_log], [row["valid_share"] for row in random_log], "s--",
                     color=COLORS["random"], ms=4, label="random: share of valid samples")
    axes[1].set(xlabel="hour", ylabel="probability", ylim=(0, 1), title="Quality of the samples")
    axes[1].legend(fontsize=7)
    fig.tight_layout()
    return fig


def plot_hardware_vs_sim(sim_share, hw_share, hw_label, names, best_k, is_valid, hour, top_n=8, ax=None):
    """Side-by-side bars: ideal simulator vs your qBraid run, for the most common on/off choices."""
    if ax is None:
        ax = plt.subplots(figsize=(8, 3.4))[1]
    top = np.argsort(-(sim_share + hw_share))[:top_n]
    x = np.arange(len(top))
    ax.bar(x - 0.2, sim_share[top], 0.38, color=COLORS["milp"], label="simulator (ideal)")
    ax.bar(x + 0.2, hw_share[top], 0.38, color=COLORS["qaoa"], label=hw_label)
    ax.set_xticks(x, [label(int(k), names) + (" (best)" if k == best_k else "")
                      + ("" if is_valid[k] else "\n(not valid)") for k in top], rotation=35, ha="right", fontsize=8)
    ax.set(ylabel="share of shots", title=f"Hour {hour}: your qBraid run vs the ideal simulator")
    ax.legend()
    return ax
