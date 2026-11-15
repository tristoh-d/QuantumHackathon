"""MILP vs the original hour-by-hour QAOA on the 5-plant benchmark day, in the pitch-deck palette.

Run from the repo root:  python presentation/charts/make_milp_vs_qaoa.py
Reads results/benchmark_5.json (24-hour on/off schedules) and data/{plants,demand}.csv,
writes PNG (1600x900) + CSV of plotted numbers into presentation/charts/slides/:
    8_hourly_cost        $/hour, MILP vs QAOA
    9_cumulative_cost    running total over the day (ends at the 7.1% gap)
    10_schedule_grid     which plants are on each hour, MILP vs QAOA, differing cells outlined
Charts carry no title: the slide headline does that.
"""
import csv
import json
import sys
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from check import hour_cost, load_demand, load_plants  # noqa: E402

OUT = Path(__file__).resolve().parent / "slides"
OUT.mkdir(exist_ok=True)

# Deck palette
YELLOW, CYAN, PINK = "#FFE600", "#8EF4F0", "#FF44CC"   # classical, quantum, warnings
BG, PANEL, BORDER, MUTED, WHITE = "#111111", "#1E1E1E", "#2A2A2A", "#9A9A9A", "#FFFFFF"
C = {"MILP": YELLOW, "QAOA": CYAN}

plt.rcParams.update({
    "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG,
    "font.size": 11, "axes.edgecolor": BORDER, "axes.labelcolor": MUTED, "xtick.color": MUTED,
    "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": BORDER, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "legend.frameon": False, "text.color": WHITE,
})
FIGSIZE, DPI = (8, 4.5), 200


def save(fig, name, header, data, note=""):
    lines = textwrap.wrap(note, 120)
    fig.get_layout_engine().set(rect=(0, 0.02 + 0.03 * len(lines), 1, 0.98 - 0.03 * len(lines) + 0.005))
    fig.text(0.01, 0.012, "\n".join(lines), color=MUTED, fontsize=8.5, ha="left", va="bottom")
    fig.savefig(OUT / f"{name}.png", dpi=DPI)
    plt.close(fig)
    with open(OUT / f"{name}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(data)
    print("wrote", name)


# ---------- data ----------
plants = load_plants()
demand, reserve = load_demand()
bench = json.load(open(ROOT / "results" / "benchmark_5.json"))["methods"]
SCHED = {"MILP": np.array(bench["MILP (optimal)"]["schedule"]),
         "QAOA": np.array(bench["QAOA, hour by hour"]["schedule"])}
TOTAL = {"MILP": bench["MILP (optimal)"]["total_cost"], "QAOA": bench["QAOA, hour by hour"]["total_cost"]}
HOURS = np.arange(24)
NAMES = [p["plant_id"].replace("_", " ").title().replace("Cc", "CC") for p in plants]


def hourly(s):
    was = [int(p["on_at_start"]) for p in plants]
    out = []
    for h in HOURS:
        out.append(hour_cost(plants, demand[h], s[h], was))
        was = s[h]
    return np.array(out)


COST = {k: hourly(s) for k, s in SCHED.items()}
for k in COST:  # must reproduce the benchmark totals
    assert abs(COST[k].sum() - TOTAL[k]) < 1, (k, COST[k].sum(), TOTAL[k])
DIFF = [h for h in HOURS if (SCHED["MILP"][h] != SCHED["QAOA"][h]).any()]
GAP = 100 * (TOTAL["QAOA"] / TOTAL["MILP"] - 1)


def shade_diff(ax):
    for h in DIFF:
        ax.axvspan(h - 0.5, h + 0.5, color=PANEL, zorder=0, lw=0)


def end_label(ax, x, y, text, color, dy=0):
    ax.annotate(text, (x, y), xytext=(8, dy), textcoords="offset points", va="center",
                color=WHITE, fontsize=11, fontweight="bold")
    ax.plot([x], [y], "o", ms=8, color=color, mec=BG, mew=2, zorder=5)


# ---------- 8: hourly cost ----------
def chart_hourly():
    fig, ax = plt.subplots(figsize=FIGSIZE, layout="constrained")
    shade_diff(ax)
    for k, lw, z in [("MILP", 2.5, 3), ("QAOA", 2.5, 4)]:
        ax.plot(HOURS, COST[k] / 1e3, color=C[k], lw=lw, zorder=z, label=k,
                solid_joinstyle="round", solid_capstyle="round")
    # direct labels at the last hour (lines coincide there, so offset vertically)
    y = COST["MILP"][-1] / 1e3
    ax.annotate("MILP (optimal)", (23, y), xytext=(8, 9), textcoords="offset points", color=WHITE,
                fontsize=10.5, fontweight="bold", va="center")
    ax.annotate("QAOA", (23, y), xytext=(8, -9), textcoords="offset points", color=WHITE,
                fontsize=10.5, fontweight="bold", va="center")
    # the two spikes are the gas combined-cycle startup: MILP at hour 5, QAOA 3 hours later
    gas = next(i for i, p in enumerate(plants) if p["plant_id"] == "GAS_CC")
    start = {k: int(np.argmax(SCHED[k][:, gas])) for k in SCHED}
    arrow = dict(arrowstyle="-", color=MUTED, lw=1)
    h = start["MILP"]
    ax.annotate(f"MILP starts the gas plant at hour {h}", (h, COST["MILP"][h] / 1e3),
                xytext=(h - 4.8, 44.5), color=WHITE, fontsize=9.5, arrowprops=arrow)
    h = start["QAOA"]
    ax.annotate(f"QAOA starts it at hour {h}, after running\npeakers + oil for hours {start['MILP']}–{h - 1}",
                (h, COST["QAOA"][h] / 1e3), xytext=(h + 1.5, 38), color=WHITE, fontsize=9.5,
                va="center", arrowprops=arrow)
    ax.set_xlim(-0.5, 26.3)
    ax.set_ylim(0, 47)
    ax.set_xticks(range(0, 24, 3))
    ax.set_xlabel("Hour of day")
    ax.set_ylabel("Cost per hour ($ thousands)")
    ax.grid(axis="x", visible=False)
    ax.legend(loc="center right", bbox_to_anchor=(1, 0.62), labelcolor=WHITE, handlelength=1.6)
    ax.text(26.3, 2, "shaded = hours the\nschedules differ", color=MUTED, fontsize=8.5, ha="right")
    save(fig, "8_hourly_cost", ["hour", "demand_mw", "milp_cost", "qaoa_cost", "schedules_differ"],
         [[h, demand[h], round(COST["MILP"][h], 2), round(COST["QAOA"][h], 2), int(h in DIFF)] for h in HOURS],
         "5-plant fleet, 24-hour benchmark day. QAOA = original hour-by-hour QAOA (p=1, 200 shots). "
         "Cost = startups + no-load + energy after economic dispatch. Source: results/benchmark_5.json")


# ---------- 9: cumulative cost ----------
def chart_cumulative():
    fig, ax = plt.subplots(figsize=FIGSIZE, layout="constrained")
    shade_diff(ax)
    cum = {k: np.cumsum(v) / 1e3 for k, v in COST.items()}
    for k in ("MILP", "QAOA"):
        ax.plot(HOURS, cum[k], color=C[k], lw=2.5, label=k, solid_capstyle="round")
    ax.fill_between(HOURS, cum["MILP"], cum["QAOA"], color=CYAN, alpha=0.12, lw=0)
    end_label(ax, 23, cum["QAOA"][-1], f"QAOA  ${cum['QAOA'][-1]:,.0f}k", C["QAOA"], dy=6)
    end_label(ax, 23, cum["MILP"][-1], f"MILP  ${cum['MILP'][-1]:,.0f}k", C["MILP"], dy=-6)
    ax.text(19.5, cum["MILP"][19] - 45, f"QAOA ends the day\n+{GAP:.1f}%  (+${(TOTAL['QAOA'] - TOTAL['MILP']) / 1e3:.1f}k)",
            color=PINK, fontsize=11, fontweight="bold", va="top", ha="center")
    ax.set_xlim(-0.5, 28.5)
    ax.set_ylim(0, 385)
    ax.set_xticks(range(0, 24, 3))
    ax.set_xlabel("Hour of day")
    ax.set_ylabel("Running cost ($ thousands)")
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper left", labelcolor=WHITE, handlelength=1.6)
    save(fig, "9_cumulative_cost", ["hour", "milp_cumulative", "qaoa_cumulative"],
         [[h, round(cum["MILP"][h] * 1e3, 2), round(cum["QAOA"][h] * 1e3, 2)] for h in HOURS],
         "Same day and schedules as the hourly chart. Shaded columns = hours where QAOA's on/off choice differs "
         "from MILP. Source: results/benchmark_5.json")


# ---------- 10: on/off grid ----------
def chart_grid():
    fig, axes = plt.subplots(2, 1, figsize=FIGSIZE, layout="constrained", sharex=True)
    n = len(plants)
    data = []
    for ax, k in zip(axes, ("MILP", "QAOA")):
        s = SCHED[k]
        other = SCHED["QAOA" if k == "MILP" else "MILP"]
        for h in HOURS:
            for i in range(n):
                on = s[h, i]
                y = n - 1 - i
                ax.add_patch(Rectangle((h + 0.06, y + 0.06), 0.88, 0.88, color=C[k] if on else PANEL, lw=0))
                if k == "QAOA" and on != other[h, i]:
                    ax.add_patch(Rectangle((h + 0.06, y + 0.06), 0.88, 0.88, fill=False, ec=PINK, lw=1.8))
                data.append([k, h, plants[i]["plant_id"], int(on)])
        ax.set_xlim(0, 24)
        ax.set_ylim(0, n)
        ax.set_yticks(np.arange(n) + 0.5, NAMES[::-1], fontsize=9.5)
        ax.tick_params(length=0)
        ax.grid(False)
        for sp in ax.spines.values():
            sp.set_visible(False)
        label = "MILP (optimal)" if k == "MILP" else f"QAOA, hour by hour  (+{GAP:.1f}% cost)"
        ax.set_title(label, loc="left", color=WHITE, fontsize=11.5, fontweight="bold", pad=4)
    axes[1].set_xticks(np.arange(0, 24, 3) + 0.5, range(0, 24, 3))
    axes[1].set_xlabel("Hour of day")
    axes[1].text(24, n + 0.15, "pink outline = differs from MILP", color=MUTED, fontsize=8.5, ha="right",
                 va="bottom")
    save(fig, "10_schedule_grid", ["method", "hour", "plant", "on"], data,
         f"Filled = plant on, dark = off. QAOA's choice differs from MILP in {len(DIFF)} of 24 hours "
         f"({', '.join(map(str, DIFF))}). Source: results/benchmark_5.json")


# ---------- 11: difference, QAOA minus MILP ----------
def chart_difference():
    # two lines (hourly cost, not running totals); pink fill = hours QAOA costs more
    fig, ax = plt.subplots(figsize=FIGSIZE, layout="constrained")
    m, q = COST["MILP"] / 1e3, COST["QAOA"] / 1e3
    xs = np.linspace(0, 23, 23 * 20 + 1)  # dense grid so the fill follows the line crossings exactly
    mi, qi = np.interp(xs, HOURS, m), np.interp(xs, HOURS, q)
    ax.fill_between(xs, mi, qi, where=qi > mi, color=PINK, alpha=0.35, lw=0, zorder=1,
                    label="QAOA costs more")
    ax.plot(HOURS, m, color=YELLOW, lw=2.5, zorder=3, label="MILP (optimal)", solid_joinstyle="round")
    ax.plot(HOURS, q, color=CYAN, lw=2.5, zorder=4, label="QAOA", solid_joinstyle="round")
    extra = (COST["QAOA"] - COST["MILP"]).clip(min=0).sum() / 1e3
    h = int(np.argmax(q - m))
    ax.annotate(f"QAOA starts the gas plant 3 h late\nand runs peakers + oil instead",
                (h + 0.3, (q[h] + m[h]) / 2 + 6), xytext=(h + 1.8, 34), color=WHITE, fontsize=9.5,
                va="center", arrowprops=dict(arrowstyle="-", color=MUTED, lw=1))
    ax.text(23, 44, f"Day total\nMILP   ${TOTAL['MILP'] / 1e3:,.0f}k\nQAOA  ${TOTAL['QAOA'] / 1e3:,.0f}k",
            color=WHITE, fontsize=11, ha="right", va="top", fontweight="bold", linespacing=1.5)
    ax.text(23, 33.5, f"+{GAP:.1f}%  (+${(TOTAL['QAOA'] - TOTAL['MILP']) / 1e3:.1f}k)",
            color=PINK, fontsize=13, ha="right", va="top", fontweight="bold")
    ax.set_xlim(-0.5, 23.5)
    ax.set_ylim(0, 46)
    ax.set_xticks(range(0, 24, 3))
    ax.set_xlabel("Hour of day")
    ax.set_ylabel("Cost per hour ($ thousands)")
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper left", labelcolor=WHITE, handlelength=1.6)
    save(fig, "11_cost_difference", ["hour", "milp_cost", "qaoa_cost", "qaoa_minus_milp"],
         [[h, round(COST["MILP"][h], 2), round(COST["QAOA"][h], 2), round(COST["QAOA"][h] - COST["MILP"][h], 2)]
          for h in HOURS],
         f"Cost of each hour's schedule (startups + no-load + energy). Pink = hours where QAOA's schedule costs "
         f"more (${extra:.1f}k in total; MILP's early gas startup at hour 5 claws some back). "
         "5-plant benchmark day. Source: results/benchmark_5.json")


if __name__ == "__main__":
    chart_difference()
    chart_hourly()
    chart_cumulative()
    chart_grid()
