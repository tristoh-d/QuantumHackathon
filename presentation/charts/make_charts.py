"""Quantum vs classical charts for the pitch deck.

Run from the repo root:  .venv/Scripts/python presentation/charts/make_charts.py
Reads results/*.csv, writes one PNG (16:9, 1600x900) and one CSV of plotted numbers per chart
into presentation/charts/.
"""
import csv
import math
import sys
import textwrap
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "results"
OUT = Path(__file__).resolve().parent

# Colors follow the entity in every chart (validated: dataviz validate_palette.js).
# Light = documents; --slides = dark steps on the pitch template's navy (#0f1d32), no chart title
# (the slide headline carries it), written to charts/slides/.
SLIDES = "--slides" in sys.argv
if SLIDES:
    OUT = OUT / "slides"
    OUT.mkdir(exist_ok=True)
    # Deck palette: yellow = classical, cyan = quantum, grays = baselines/chrome on #111111.
    # Gold / deep teal / #666 are darker steps added so co-plotted series stay CVD-separable.
    C = {"QAOA": "#8EF4F0", "QAOA_p1": "#00B3AD", "Random": "#666666", "Rule": "#D4A72C",
         "MILP": "#FFE600", "SA": "#D4A72C"}
    SURFACE, INK, INK2, GRID, SHADE = "#111111", "#FFFFFF", "#9A9A9A", "#2A2A2A", "#1E1E1E"
else:
    C = {"QAOA": "#2a78d6", "QAOA_p1": "#86b6ef", "Random": "#eb6834", "Rule": "#1baf7a",
         "MILP": "#6250d6", "SA": "#eda100"}
    SURFACE, INK, INK2, GRID, SHADE = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df", "#ecebe7"
FAMILY_C = ({"market_split": "#FFE600", "interaction": "#D4A72C", "symmetric": "#9A9A9A"} if SLIDES else
            {"market_split": C["QAOA"], "interaction": C["Random"], "symmetric": C["Rule"]})
FIGSIZE = (8, 4.5) if SLIDES else (10, 5.625)  # both 1600x900 px; slides get larger relative text
DPI = 200 if SLIDES else 160

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.size": 11, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2,
    "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlecolor": INK,
    "axes.titlelocation": "left", "legend.frameon": False, "text.color": INK,
})


def rows(name):
    with open(RES / name, newline="") as f:
        return list(csv.DictReader(f))


def boot_ci(x, n=2000, seed=0):
    x = np.asarray(x, float)
    rng = np.random.default_rng(seed)
    means = rng.choice(x, (n, len(x))).mean(axis=1)
    return x.mean(), np.percentile(means, 2.5), np.percentile(means, 97.5)


def save(fig, name, header, data, note=""):
    lines = textwrap.wrap(note, 120 if SLIDES else 150)
    fig.get_layout_engine().set(rect=(0, 0.02 + 0.03 * len(lines), 1, 0.98 - 0.03 * len(lines) + 0.005))
    fig.text(0.01, 0.012, "\n".join(lines), color=INK2, fontsize=8.5, ha="left", va="bottom")
    fig.savefig(OUT / f"{name}.png", dpi=DPI)
    plt.close(fig)
    with open(OUT / f"{name}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(data)
    print("wrote", name)


def new_fig(title, **kw):
    fig, ax = plt.subplots(figsize=FIGSIZE, layout="constrained", **kw)
    if not SLIDES:
        fig.suptitle(title, x=0.01, ha="left", fontsize=15, fontweight="bold", color=INK)
    return fig, ax


# ---------- 1 & 2: TVA days, valid days and cost gap (5- and 10-plant fleets) ----------
def tva_summary(fname, few, enough):
    by = defaultdict(list)
    for r in rows(fname):
        key = ("Rule", "") if r["method"] == "rule" else (
            "QAOA" if r["method"] == "qaoa" else "Random", r["shots"])
        by[key].append(r)
    out = []
    for key in [("Rule", ""), ("Random", few), ("QAOA", few), ("Random", enough), ("QAOA", enough)]:
        rs = by[key]
        valid = sum(int(r["valid"]) for r in rs)
        m, lo, hi = boot_ci([float(r["gap_pct"]) for r in rs])
        out.append((key[0], key[1], valid, len(rs), m, lo, hi))
    return out


def chart_valid_days():
    s5 = tva_summary("tva_quantum5.csv", "20", "200")
    s10 = tva_summary("tva_quantum10.csv", "200", "1000")
    fig, axes = new_fig("QAOA finds rule-abiding schedules more often than random or the rule", ncols=2, sharey=True)
    data = []
    for ax, s, title in [(axes[0], s5, "5 plants (32 choices / hour)"),
                         (axes[1], s10, "10 plants (1,024 choices / hour)")]:
        labels, vals, cols = [], [], []
        for meth, shots, valid, n, *_ in s:
            labels.append("Rule" if meth == "Rule" else f"{meth}\n{shots}")
            vals.append(valid)
            cols.append(C[meth])
            data.append([title, meth, shots, valid, n])
        x = np.arange(len(vals))
        ax.bar(x, vals, color=cols, width=0.7, edgecolor=SURFACE, linewidth=2)
        for xi, v in zip(x, vals):
            ax.text(xi, v + 0.8, f"{v}", ha="center", color=INK, fontsize=12, fontweight="bold")
        ax.axhline(40, color=C["MILP"], lw=1.5, ls="--")
        ax.text(-0.45, 44.2, "- - MILP: valid on all 40", color=INK2, fontsize=9.5)
        ax.set_xticks(x, labels, fontsize=9.5)
        ax.set_title(title, fontsize=13)
        ax.set_ylim(0, 47)
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("Valid days out of 40")
    save(fig, "1_valid_days", ["fleet", "method", "shots", "valid_days", "days"], data,
         "Numbers under bars = shots per hour; Rule = cheapest-first. 40 real TVA days (EIA-930), scaled to each fleet. "
         "Valid = meets demand, reserve, min up / min down. "
         "Source: results/tva_quantum5.csv, tva_quantum10.csv")


def chart_cost_gap():
    s10 = tva_summary("tva_quantum10.csv", "200", "1000")
    s5 = tva_summary("tva_quantum5.csv", "20", "200")
    fig, axes = new_fig("Every sampled method costs more than the classical optimum (MILP = 0%)", ncols=2, sharex=True)
    data = []
    for ax, s, title in [(axes[0], s5, "5 plants"), (axes[1], s10, "10 plants")]:
        s = s[::-1]
        y = np.arange(len(s))
        for yi, (meth, shots, valid, n, m, lo, hi) in zip(y, s):
            ax.barh(yi, m, color=C[meth], height=0.6, edgecolor=SURFACE, linewidth=2)
            ax.errorbar(m, yi, xerr=[[m - lo], [hi - m]], color=INK2, capsize=3, lw=1)
            ax.text(hi + 0.8, yi, f"+{m:.1f}%", va="center", color=INK, fontsize=11)
            data.append([title, meth, shots, round(m, 2), round(lo, 2), round(hi, 2), valid, n])
        ax.set_yticks(y, ["Cheapest-first rule" if mm == "Rule" else f"{mm}, {sh} shots"
                          for mm, sh, *_ in s], fontsize=10.5)
        ax.set_title(title, fontsize=13)
        ax.axvline(0, color=C["MILP"], lw=2)
        ax.grid(axis="y", visible=False)
        ax.set_xlim(0, 48)
        ax.set_xlabel("% above MILP cost, mean of 40 days")
    save(fig, "2_cost_gap", ["fleet", "method", "shots", "mean_gap_pct", "ci_lo", "ci_hi", "valid_days", "days"],
         data, "Whiskers: 95% bootstrap CI over 40 TVA days. Rule is cheapest but breaks min up / min down times "
         "(see chart 1). Source: results/tva_quantum5.csv, tva_quantum10.csv")


# ---------- 3: shots sweep, hours matching the hour's best ----------
def chart_shots():
    T = "QAOA's edge over random is largest when shots are scarce"
    agg = defaultdict(list)
    for r in rows("shots_sweep.csv"):
        agg[(r["sampler"], int(r["shots"]))].append(float(r["hours_matching_best"]))
    fig, ax = new_fig(T)
    data = []
    for s, name in [("qaoa", "QAOA"), ("random", "Random")]:
        xs = sorted(k[1] for k in agg if k[0] == s)
        ys = [np.mean(agg[(s, x)]) for x in xs]
        ax.plot(xs, ys, color=C[name], lw=2, marker="o", ms=8, mec=SURFACE, mew=2)
        ax.text(xs[2] * 1.12, ys[2] + (0.9 if name == "QAOA" else -2.2), name,
                color=INK, fontsize=12, fontweight="bold")
        data += [[name, x, round(y, 2)] for x, y in zip(xs, ys)]
    ax.set_xscale("log")
    ax.set_xticks([5, 10, 20, 50, 200], ["5", "10", "20", "50", "200"])
    ax.set_xlim(4, 400)
    ax.set_ylim(0, 25.5)
    ax.axhline(24, color=GRID, lw=1)
    ax.axvspan(120, 400, color=SHADE, zorder=0)
    ax.text(128, 3, "Shots cover all 32 choices:\nthe classical scoring step\ndoes the work", color=INK2, fontsize=10.5)
    ax.set_xlabel("Shots per hour (log scale)")
    ax.set_ylabel("Hours that pick the hour's best choice (of 24)")
    save(fig, "3_shots_sweep", ["sampler", "shots", "mean_hours_matching_best"], data,
         "5-plant fleet, p=1, mean of 5 seeds. Source: results/shots_sweep.csv")


# ---------- 4: time to a schedule ----------
def chart_time():
    tva = rows("tva_classical.csv")
    milp20 = np.mean([float(r["milp_seconds"]) for r in tva])
    items = [  # (label, seconds, entity) from docs/results.md "Timing" and tva_* runs
        ("MILP, 5 plants", 0.08, "MILP"),
        ("MILP, 10 plants", 0.08, "MILP"),
        ("MILP, 20 TVA plants", milp20, "MILP"),
        ("QAOA, 5 plants (simulator)", 3.8, "QAOA"),
        ("QAOA, 10 plants (simulator)", 10.5, "QAOA"),
        ("One hour on IonQ cloud sim,\nsubmit to result", 15, "QAOA"),
    ]
    fig, ax = new_fig("The exact classical solver is 50–130× faster per day")
    y = np.arange(len(items))[::-1]
    for yi, (lab, s, e) in zip(y, items):
        ax.barh(yi, s, color=C[e], height=0.6, edgecolor=SURFACE, linewidth=2)
        ax.text(s * 1.15, yi, f"{s:.2g} s", va="center", color=INK, fontsize=11)
    ax.set_yticks(y, [i[0] for i in items], fontsize=10.5)
    ax.set_xscale("log")
    ax.set_xlim(0.03, 100)
    ax.set_xticks([0.1, 1, 10, 100], ["0.1", "1", "10", "100"])
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Seconds (log scale)")
    save(fig, "4_time", ["step", "seconds", "kind"], [[i[0].replace("\n", " "), round(i[1], 3), i[2]] for i in items],
         "Full day = 24 hours. The cloud-simulator line is ONE hour incl. queue; a real QPU queue is hours. "
         "Source: docs/results.md (Timing), results/tva_classical.csv")


# ---------- 5: hard cases, MILP time vs size ----------
def chart_milp_hardness():
    agg = defaultdict(list)
    for r in rows("hardness_milp.csv"):
        agg[(r["family"], int(r["n"]))].append(float(r["seconds"]))
    fig, ax = new_fig("The MILP only struggles past the sizes we can simulate exactly")
    data = []
    ax.axvspan(7, 22, color=SHADE, zorder=0)
    ax.text(7.5, 0.007, "Exact QAOA simulation\npossible (n ≤ 22)", color=INK2, fontsize=10, va="bottom")
    ax.axhline(30, color=INK2, lw=1, ls="--")
    ax.text(7.5, 36, "30 s limit (timed out)", color=INK2, fontsize=9.5, va="bottom")
    names = {"market_split": "Market split", "interaction": "Pairwise interaction", "symmetric": "Identical units"}
    for fam in ["market_split", "interaction", "symmetric"]:
        xs = sorted(n for f, n in agg if f == fam)
        ys = [np.median(agg[(fam, n)]) for n in xs]
        ax.plot(xs, ys, color=FAMILY_C[fam], lw=2, marker="o", ms=7, mec=SURFACE, mew=2)
        ax.text(xs[-1] + 0.8, {"market_split": 19, "interaction": 47, "symmetric": ys[-1]}[fam],
                names[fam], color=INK, fontsize=11, va="center")
        data += [[fam, x, round(y, 4)] for x, y in zip(xs, ys)]
    ax.text(50.8, 11.5, "(both time out from n = 30–35)", color=INK2, fontsize=9.5, va="center")
    ax.set_yscale("log")
    ax.set_xlim(7, 62)
    ax.set_ylim(0.005, 80)
    ax.set_xlabel("Plants (n)")
    ax.set_ylabel("MILP solve time, median of 5 (s, log)")
    save(fig, "5_milp_hardness", ["family", "n", "median_seconds"], data,
         "HiGHS via scipy, 5 seeds per size, CPU shared with other runs. Source: results/hardness_milp.csv")


# ---------- 6: hard cases, chance one sample is optimal ----------
def chart_p_opt():
    fams = [("market_split", "Market split"), ("interaction", "Pairwise interaction")]
    fig, axes = new_fig("QAOA beats random by a fixed factor that does not grow with size", ncols=2, sharey=True)
    data = []
    series = [("random", "Random", C["Random"]), ("qaoa_p1", "QAOA p=1", C["QAOA_p1"]),
              ("qaoa_p3", "QAOA p=3", C["QAOA"]), ("sa", "Sim. annealing (per run)", C["SA"])]
    for ax, (fam, title) in zip(axes, fams):
        agg = defaultdict(list)
        for r in rows(f"hardness_quantum_{fam}.csv"):
            agg[(r["method"], int(r["n"]))].append(float(r["p_success"]))
        for meth, lab, col in series:
            xs = sorted(n for m, n in agg if m == meth)
            pts = []
            for n in xs:
                raw = agg[(meth, n)]
                hits = sum(p > 0 for p in raw)
                v = [max(p, 0.5 / 1000) for p in raw] if meth == "sa" else raw  # SA: 0 hits counted as 0.5
                g = math.exp(np.mean(np.log(v)))
                pts.append((n, g, hits == len(raw)))
                data.append([fam, lab, n, len(raw), hits, f"{g:.3e}"])
            px, py, full = zip(*pts)
            ax.plot(px, py, color=col, lw=2, ls="--" if meth == "qaoa_p1" else "-", marker="o", ms=6,
                    mec=SURFACE, mew=1.5, label=lab)
            hol = [(x, y) for x, y, f in pts if not f]
            if hol:  # some instances never solved: value leans on the 0.5-hit floor
                ax.plot(*zip(*hol), ls="none", marker="o", ms=8, mfc=SURFACE, mec=col, mew=2)
        ax.set_yscale("log")
        ax.set_title(title, fontsize=13)
        ax.set_xlabel("Plants (n)")
        ax.set_xticks(range(8, 23, 2))
    axes[0].set_ylabel("Chance one sample is optimal (log)")
    axes[0].legend(loc="lower left", fontsize=9.5)
    save(fig, "6_p_opt", ["family", "method", "n", "seeds", "seeds_with_hits", "geo_mean_p_opt"], data,
         "Exact statevector, geometric mean over seeds (n=22: 3). QAOA/random per shot; SA per 1,000-sweep run. "
         "Hollow = some instances never solved in 1,000 SA runs (counted as 0.5).")


# ---------- 7: noise on simulated hardware ----------
def chart_noise():
    configs = [("ideal-p1", "Noise-free"), ("forte-p1", "IonQ Forte noise"),
               ("noisy-p1", "2% gate error"), ("vnoisy-p1", "5% gate error"), ("random", "Random guessing")]
    fig, ax = new_fig("Hardware noise pushes QAOA toward random, gradually")
    data = []
    for i, (cfg, lab) in enumerate(configs):
        rs = [r for r in rows(f"tva_sims_{cfg}.csv") if r["shots"] == "20"]
        share = np.mean([float(r["mean_valid_share"]) for r in rs])
        valid = sum(int(r["valid"]) for r in rs)
        col = C["Random"] if cfg == "random" else C["QAOA"]
        ax.bar(i, share, color=col, width=0.65, edgecolor=SURFACE, linewidth=2)
        ax.text(i, share + 0.01, f"{share:.2f}\n{valid}/40 valid days", ha="center", color=INK, fontsize=10.5)
        data.append([cfg, round(share, 3), valid, len(rs)])
    ax.set_xticks(range(len(configs)), [c[1] for c in configs], fontsize=10.5)
    ax.set_ylim(0, 0.45)
    ax.grid(axis="x", visible=False)
    ax.set_ylabel("Share of shots that are valid")
    save(fig, "7_noise", ["config", "mean_valid_shot_share", "valid_days", "days"], data,
         "5-plant fleet, p=1, 20 shots, 40 TVA days. Angles tuned noise-free; noise via Aer density matrix. "
         "Source: results/tva_sims_*.csv")


if __name__ == "__main__":
    chart_valid_days()
    chart_cost_gap()
    chart_shots()
    chart_time()
    chart_milp_hardness()
    chart_p_opt()
    chart_noise()
