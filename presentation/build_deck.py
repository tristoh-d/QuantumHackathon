"""Fill the organizers' five-slide template with our story and charts (+ backup slides).

Needs python-pptx (not in requirements.txt):  pip install python-pptx
Run from the repo root after the slide charts exist:
    .venv/Scripts/python presentation/charts/make_charts.py --slides
    python presentation/build_deck.py
"""
import copy
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "presentation" / "Quantum_Hackathon_Five_Slide_Genric-Template.pptx"
OUT = REPO / "presentation" / "QuantumUC_pitch.pptx"
CH = REPO / "presentation" / "charts" / "slides"

ACCENT = RGBColor(0x7D, 0xBE, 0xF5)   # template kicker blue
BODY = RGBColor(0xDA, 0xE6, 0xF5)     # template body text
MUTED = RGBColor(0x82, 0x9B, 0xB4)    # template footer
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
CARD = RGBColor(0x18, 0x2B, 0x45)     # one step lighter than the 0F1D32 background

prs = Presentation(TEMPLATE)
slides = list(prs.slides)


def shape(slide, name):
    return next(s for s in slide.shapes if s.name == name)


def set_text(sh, text, size=None):
    r = sh.text_frame.paragraphs[0].runs[0]
    r.text = text
    if size:
        r.font.size = Pt(size)


def drop_bullets(slide):
    for n in ("TextBox 3", "TextBox 4", "TextBox 5"):
        el = shape(slide, n)._element
        el.getparent().remove(el)


def bullets(slide, items, x, y, w, h, size=16):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tb.name = "Body"
    tf = tb.text_frame
    tf.word_wrap = True
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        lead, _, rest = item.partition("|")  # "Bold lead|rest of the line"
        pPr = p._p.get_or_add_pPr()
        pPr.set("marL", str(Inches(0.25)))
        pPr.set("indent", str(-Inches(0.25)))
        bu = pPr.makeelement(qn("a:buChar"), {"char": "•"})
        pPr.append(bu)
        p.space_after = Pt(9)
        if rest:
            r = p.add_run()
            r.text = lead + " "
            r.font.bold = True
            r.font.size = Pt(size)
            r.font.color.rgb = WHITE
        r = p.add_run()
        r.text = rest if rest else lead
        r.font.size = Pt(size)
        r.font.color.rgb = BODY
    return tb


def stat(slide, x, y, w, h, big, label, name):
    card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    card.name = f"Card {name}"
    card.adjustments[0] = 0.08
    card.fill.solid()
    card.fill.fore_color.rgb = CARD
    card.line.fill.background()
    card.shadow.inherit = False
    tf = card.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = tf.margin_right = Inches(0.3)
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    r = p.add_run()
    r.text = big
    r.font.size = Pt(40)
    r.font.bold = True
    r.font.color.rgb = ACCENT
    p2 = tf.add_paragraph()
    p2.alignment = PP_ALIGN.LEFT
    r = p2.add_run()
    r.text = label
    r.font.size = Pt(14)
    r.font.color.rgb = BODY


def chart(slide, fname, x, y, w, alt):
    pic = slide.shapes.add_picture(str(CH / fname), Inches(x), Inches(y), width=Inches(w))
    pic.name = f"Chart {fname}"
    pic._element.nvPicPr.cNvPr.set("descr", alt)
    return pic


def notes(slide, text):
    slide.notes_slide.notes_text_frame.text = text


# ---------------- 1 / THE PROBLEM ----------------
s = slides[0]
set_text(shape(s, "TextBox 2"), "Which plants should run each hour?")
drop_bullets(s)
bullets(s, [
    "Unit commitment:|choose which power plants are on each hour, to meet demand plus a 10% reserve at the lowest cost.",
    "Hours are linked:|startup costs and minimum up / down times mean one hour's choice shapes the rest of the day.",
    "Shortcuts fail:|a cheapest-first rule of thumb costs more and breaks the operating rules.",
    "Today:|exact MILP solvers already do this well. Our question: can quantum (QAOA) add anything?",
], 0.8, 2.45, 6.6, 4.2, size=17)
stat(s, 7.9, 2.45, 4.6, 1.25, "+5.4%", "cheapest-first rule above the optimum, 240 real TVA days", "rule gap")
stat(s, 7.9, 3.85, 4.6, 1.25, "91%", "of those days the rule breaks a min up / down time", "rule breaks")
stat(s, 7.9, 5.25, 4.6, 1.25, "0.8 s", "exact MILP solve, 20 TVA plants × 24 hours", "milp time")
notes(s, "Unit commitment = deciding which plants are on each hour. Demand plus 10% reserve must be met at least cost; "
         "startups cost money and plants have minimum up and down times, so the hours are coupled. "
         "On 240 real TVA demand days (EIA-930, 20-plant TVA fleet) the cheapest-first rule averages +5.43% over the "
         "MILP optimum and breaks a min up/down time on 91% of days. The MILP solves each day in 0.79 s on average. "
         "Source: docs/results.md, 'Classical: MILP vs cheapest-first rule'.")

# ---------------- 2 / CUSTOMER ----------------
s = slides[1]
set_text(shape(s, "TextBox 2"), "Day-ahead schedulers at big utilities")
drop_bullets(s)
bullets(s, [
    "Customer:|utilities that commit thermal fleets a day ahead, like TVA (20 coal and gas plants in our data).",
    "End user:|generation schedulers. Decision maker: the head of power operations.",
    "What they use today:|a MILP solver: exact, and under a second per day on TVA’s fleet.",
    "To trust a new method:|valid schedules every day, a known cost gap, and answers in minutes, hardware queue included.",
], 0.8, 2.45, 6.6, 4.2, size=17)
stat(s, 7.9, 2.45, 4.6, 1.9, "$4.48B", "TVA fuel + purchased power expense, FY2025 (TVA year-end results)", "fuel")
stat(s, 7.9, 4.55, 4.6, 1.9, "≈ $45M / yr", "what a 1% change would mean. A scenario, not savings we achieved", "scenario")
notes(s, "Value scenario: TVA reported fuel and purchased power expense of $4,482M in FY2025 (vs $3,750M in FY2024), "
         "from TVA's FY25 investor press release. 1% of that is about $45M per year. Unit commitment affects mainly "
         "the fuel part (about $2.4B; purchased power about $2.1B), so 1% of fuel alone is about $24M. "
         "This is a scenario to show the stakes, not a claim: our QAOA method does not beat the MILP today. "
         "We did not scale the toy day to TVA size.")

# ---------------- 3 / SOLUTION ----------------
s = slides[2]
set_text(shape(s, "TextBox 2"), "QAOA picks plants; classical code checks")
drop_bullets(s)
bullets(s, [
    "Method:|each hour is a QUBO, one qubit per plant plus slack qubits (8 qubits for 5 plants, 13 for 10).",
    "Loop:|QAOA samples on/off choices; we keep the cheapest valid one and move to the next hour.",
    "Tested:|40 real TVA days, two fleets, plus simulated IonQ Forte noise.",
    "Works:|valid schedules on 38–39 of 40 days, vs 22 for random and for the rule (10 plants).",
    "Unproven:|cost: every sampled method stays 5 to 25% above the MILP (backup A1).",
], 0.8, 2.35, 4.6, 4.4, size=15)
chart(s, "1_valid_days.png", 5.65, 2.45, 7.2,
      "Bar chart: valid days out of 40. 5 plants: rule 25, random 20 shots 7, QAOA 20 shots 19, both 40 at 200 shots. "
      "10 plants: rule 22, random 200 shots 22, QAOA 200 shots 38, random 1000 shots 37, QAOA 1000 shots 39. MILP 40.")
notes(s, "Each hour becomes a QUBO: plant bits plus slack bits that turn the demand-and-reserve inequality into an "
         "equality penalty. QAOA p=1 samples bitstrings; the classical step scores each sampled choice exactly and keeps "
         "the cheapest valid one. Chart: on 10 plants (1,024 choices an hour) QAOA at 200 shots gives a valid day on "
         "38 of 40 TVA days vs 22 for random and 22 for the cheapest-first rule. On 5 plants, 200 shots see all 32 "
         "choices, so QAOA and random tie. Cost: QAOA 1000 shots +15.2% vs random +16.5% over the MILP (10 plants). "
         "Source: results/tva_quantum5.csv, tva_quantum10.csv.")

# ---------------- 4 / TEAM ----------------
s = slides[3]
for n, t in [("TextBox 3", "•  [Name]: [expertise], [what they built]"),
             ("TextBox 4", "•  [Name]: [expertise], [what they built]"),
             ("TextBox 5", "•  [Name]: [expertise], [what they built]")]:
    set_text(shape(s, n), t)

# ---------------- 5 / WHAT WE LEARNED ----------------
s = slides[4]
set_text(shape(s, "TextBox 2"), "No quantum win, and we can show why")
drop_bullets(s)
bullets(s, [
    "Validated:|QAOA samples better than random (2–3× more valid shots), and IonQ Forte-level noise barely hurts.",
    "Disproved:|any cost or speed edge here. The MILP is optimal and 50–130× faster.",
    "Surprise:|on known-hard cases the MILP only slows past 25–30 plants; we can only simulate exactly up to 22.",
    "Next:|plan the whole day at once (plants × 24 qubits) and test 30+ plant hard cases on GPU simulators.",
], 0.8, 2.35, 4.6, 4.4, size=15)
chart(s, "5_milp_hardness.png", 5.65, 2.45, 7.2,
      "Line chart, log scale: MILP solve time vs plants. Market split and pairwise interaction rise from 0.02-0.15 s at "
      "10 plants to the 30 s limit at 30 plants; identical units stay under 0.1 s. Exact QAOA simulation covers n <= 22.")
notes(s, "Validated: QAOA's samples beat random. 2–3x the share of valid shots on 10 plants, and IonQ Forte-level noise "
         "leaves the valid-shot share unchanged (0.34 vs 0.34). Disproved: a cost or speed edge. The MILP takes 0.08 s "
         "per day vs 3.8–10.5 s for hour-by-hour QAOA on a simulator. Surprise (chart): we built cases known to be hard "
         "for MILP (market split, pairwise interaction, identical units). The MILP times out from 30 plants, but exact "
         "QAOA simulation stops at 22, and there QAOA beats random by only a fixed 2–5.5x factor (backup A4). "
         "Next: a whole-day formulation, since hour-by-hour leaves 5–15% on the table. "
         "Source: docs/results.md, 'Where MILP struggles'.")

# ---------------- Backup slides ----------------
blank = slides[0].slide_layout
src = slides[0]
BACKUP = [
    ("A1", "Every sampled method costs more than the MILP", "2_cost_gap.png",
     "Horizontal bars: % above MILP cost on 40 TVA days. 5 plants: rule 5.9, random 20 shots 27.5, QAOA 20 shots 22.6, "
     "random 200 shots 4.6, QAOA 200 shots 4.9. 10 plants: rule 4.6, random 200 shots 36.3, QAOA 200 shots 25.1, "
     "random 1000 shots 16.5, QAOA 1000 shots 15.2.",
     "Cost gap above the MILP optimum on 40 TVA days, with 95% bootstrap CIs. The rule is cheapest but invalid on "
     "15–18 of 40 days. QAOA beats random clearly only when shots are scarce (10 plants, 200 shots: +25.1% vs +36.3%)."),
    ("A2", "QAOA’s edge is largest when shots are scarce", "3_shots_sweep.png",
     "Line chart: hours that pick the hour's best choice vs shots, 5 plants. QAOA 5, 12.6, 18.4, 21.8, 24 at 5, 10, 20, "
     "50, 200 shots; random 3, 5, 11.4, 19, 24.",
     "Five-plant fleet, 5 seeds. With 200 shots both samplers see all 32 choices per hour, so the classical scoring step "
     "does the work and they tie. Source: results/shots_sweep.csv."),
    ("A3", "The MILP is 50–130× faster per day", "4_time.png",
     "Bar chart, log scale: MILP 0.08 s for 5 and 10 plants, 0.79 s for 20 TVA plants; QAOA on a simulator 3.8 s and "
     "10.5 s per day; one hour on the IonQ cloud simulator 15 s submit to result.",
     "Wall time per scheduling day. QAOA times include the classical scoring inside the loop. The 15 s is one hour "
     "on IonQ's cloud simulator, queue included; a real QPU queue is hours. Source: docs/results.md, Timing."),
    ("A4", "QAOA’s edge over random doesn’t grow with size", "6_p_opt.png",
     "Two log-scale line charts, market split and pairwise interaction, n = 8 to 22: chance one sample is optimal for "
     "random, QAOA p=1, QAOA p=3 and simulated annealing. All fall about 2x per added plant; QAOA p=3 stays 2-5x above "
     "random; annealing stays highest.",
     "Exact noise-free statevector. QAOA p=3 is 2–4x (market split) to 4–5.5x (interaction) more likely than random "
     "to return the optimum, at every size, so the curves stay parallel. At 22 plants that is about 1e-6 per shot: "
     "~4–5 million shots for a 99% chance. Source: results/hardness_quantum_*.csv."),
    ("A5", "Noise pushes QAOA toward random, gradually", "7_noise.png",
     "Bar chart: share of valid shots, 5 plants, 20 shots: noise-free 0.34, IonQ Forte noise 0.34, 2% gate error 0.30, "
     "5% gate error 0.27, random 0.19.",
     "Five-plant fleet, p=1, 20 shots, 40 TVA days. Forte-level noise leaves sample quality unchanged; even 5% "
     "two-qubit error stays above random. Source: results/tva_sims_*.csv."),
]
for code, head, img, alt, note in BACKUP:
    s = prs.slides.add_slide(blank)
    bg = src._element.cSld.find(qn("p:bg"))
    s._element.cSld.insert(0, copy.deepcopy(bg))
    for n in ("TextBox 1", "TextBox 2", "TextBox 6"):
        s.shapes._spTree.append(copy.deepcopy(shape(src, n)._element))
    set_text(shape(s, "TextBox 1"), f"BACKUP / {code}")
    set_text(shape(s, "TextBox 2"), head, size=32)
    chart(s, img, (13.333 - 8.1) / 2, 2.2, 8.1, alt)
    notes(s, note)

prs.save(OUT)
print("saved", OUT, len(prs.slides), "slides")
