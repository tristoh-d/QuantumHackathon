import sys

import matplotlib
if "--save" in sys.argv:
    matplotlib.use("Agg")

import matplotlib.animation as animation
import matplotlib.pyplot as plt
import networkx as nx
from matplotlib.patches import Rectangle, FancyBboxPatch, Polygon, Ellipse
from matplotlib import font_manager

# ---------------------------------------------------------------- Palette
PARCHMENT   = "#f0e2bd"
PARCHMENT_2 = "#e6d3a3"
INK         = "#2b1d12"
SEPIA       = "#6b4f33"
TYRIAN      = "#5b2a86"   # nuclear plant purple
TYRIAN_DARK = "#3a1a57"
TYRIAN_LITE = "#8a5cb8"
LAPIS       = "#26428b"   # idle customers
VERDIGRIS   = "#2f7d5b"   # customer under evaluation
GOLD        = "#c9a227"   # winner / gold leaf
VERMILION   = "#b7410e"

# Pick the most "old-world" serif available
preferred = ["Palatino Linotype", "Book Antiqua", "Palatino", "Garamond",
             "EB Garamond", "Georgia", "Times New Roman", "DejaVu Serif"]
installed = {f.name for f in font_manager.fontManager.ttflist}
FONT = next((f for f in preferred if f in installed), "serif")
plt.rcParams["font.family"] = FONT

# ---------------------------------------------------------------- Data
customers = [
    {"name": "Customer 1", "price": 22.0},
    {"name": "Customer 2", "price": 38.0},
    {"name": "Customer 3", "price": 45.0},
    {"name": "Customer 4", "price": 85.0},
    {"name": "Customer 5", "price": 30.0},
]
lowest_cust = min(customers, key=lambda x: x["price"])

nuclear_node = "Nuclear Plant"
positions = {
    nuclear_node: (-3.0, 0.0),
    "Customer 1": (3.0, 2.0),
    "Customer 2": (3.0, 1.0),
    "Customer 3": (3.0, 0.0),
    "Customer 4": (3.0, -1.0),
    "Customer 5": (3.0, -2.0),
}

G = nx.Graph()
G.add_node(nuclear_node, pos=positions[nuclear_node])
for c in customers:
    G.add_node(c["name"], pos=positions[c["name"]])
    G.add_edge(c["name"], nuclear_node)
pos = nx.get_node_attributes(G, "pos")

# ---------------------------------------------------------------- Figure
fig, ax = plt.subplots(figsize=(11, 7.6))
fig.patch.set_facecolor(PARCHMENT)
ax.set_facecolor(PARCHMENT)
ax.set_xlim(-5.4, 5.4)
ax.set_ylim(-4.0, 4.0)
ax.set_aspect("equal")
ax.axis("off")

# Parchment vignette: soft darker corners
for i, a in enumerate([0.10, 0.07, 0.05, 0.03]):
    inset = 0.25 * i
    ax.add_patch(Rectangle((-5.4 + inset, -4.0 + inset), 10.8 - 2 * inset, 8.0 - 2 * inset,
                           fill=False, edgecolor=SEPIA, linewidth=14 - 3 * i,
                           alpha=a, zorder=0))

# Double ruled border with corner ornaments
ax.add_patch(Rectangle((-5.2, -3.8), 10.4, 7.6, fill=False, edgecolor=INK, lw=2.6, zorder=1))
ax.add_patch(Rectangle((-5.05, -3.65), 10.1, 7.3, fill=False, edgecolor=INK, lw=0.8, zorder=1))
for sx in (-1, 1):
    for sy in (-1, 1):
        ax.scatter([sx * 5.12], [sy * 3.72], marker="D", s=70, c=GOLD,
                   edgecolors=INK, linewidths=1.0, zorder=3)

# Title and subtitle
ax.text(0, 3.38, "The Power Grid of the Tennessee Valley",
        fontsize=21, fontweight="bold", color=INK, ha="center", va="center",
        style="italic", zorder=5)
ax.text(0, 2.95, "~  A Reckoning of Bids Laid Before the Atomic Forge  ~",
        fontsize=11.5, color=SEPIA, ha="center", va="center", style="italic", zorder=5)
ax.plot([-3.2, 3.2], [3.12, 3.12], color=INK, lw=0.9, zorder=2)
ax.plot([-3.2, 3.2], [3.08, 3.08], color=INK, lw=0.4, zorder=2)

# ---------------------------------------------------------------- Edges
# Drawn as inked lines with a faint shadow, via networkx
nx.draw_networkx_edges(G, pos, ax=ax, width=3.2, edge_color=PARCHMENT_2, alpha=0.9)
edge_lines = nx.draw_networkx_edges(G, pos, ax=ax, width=1.5, edge_color=SEPIA,
                                    style=(0, (5, 3)))

# ---------------------------------------------------------------- Nuclear plant: a purple keep
nx0, ny0 = pos[nuclear_node]
w, h = 1.9, 1.7
# Drop shadow
ax.add_patch(Rectangle((nx0 - w / 2 + 0.08, ny0 - h / 2 - 0.08), w, h,
                       facecolor=INK, alpha=0.25, zorder=2, edgecolor="none"))
# Main wall
ax.add_patch(Rectangle((nx0 - w / 2, ny0 - h / 2), w, h, facecolor=TYRIAN,
                       edgecolor=INK, lw=2.2, zorder=3))
# Stone coursing
for k in range(1, 6):
    yy = ny0 - h / 2 + k * h / 6
    ax.plot([nx0 - w / 2, nx0 + w / 2], [yy, yy], color=TYRIAN_DARK, lw=0.7, alpha=0.7, zorder=4)
# Crenellations
n_cren = 5
cw = w / (2 * n_cren - 1)
for k in range(n_cren):
    ax.add_patch(Rectangle((nx0 - w / 2 + 2 * k * cw, ny0 + h / 2), cw, 0.22,
                           facecolor=TYRIAN, edgecolor=INK, lw=1.6, zorder=3))
# Gothic arched door
door_w, door_h = 0.5, 0.65
ax.add_patch(Rectangle((nx0 - door_w / 2, ny0 - h / 2), door_w, door_h,
                       facecolor=TYRIAN_DARK, edgecolor=INK, lw=1.4, zorder=5))
ax.add_patch(Polygon([[nx0 - door_w / 2, ny0 - h / 2 + door_h],
                      [nx0 + door_w / 2, ny0 - h / 2 + door_h],
                      [nx0, ny0 - h / 2 + door_h + 0.28]],
                     closed=True, facecolor=TYRIAN_DARK, edgecolor=INK, lw=1.4, zorder=5))
# Atom emblem in gold leaf above the door (drawn from shapes, no font needed)
ax_c = (nx0, ny0 + 0.42)
ax.add_patch(plt.Circle(ax_c, 0.36, facecolor=GOLD, edgecolor=INK, lw=1.6, zorder=5))
for ang in (0, 60, 120):
    ax.add_patch(Ellipse(ax_c, 0.62, 0.22, angle=ang, fill=False,
                         edgecolor=TYRIAN_DARK, lw=1.3, zorder=6))
ax.add_patch(plt.Circle(ax_c, 0.06, facecolor=TYRIAN_DARK, edgecolor=INK, lw=0.8, zorder=7))
# Name banner
ax.add_patch(FancyBboxPatch((nx0 - 1.35, ny0 - h / 2 - 0.62), 2.7, 0.4,
                            boxstyle="round,pad=0.02,rounding_size=0.08",
                            facecolor=PARCHMENT_2, edgecolor=INK, lw=1.4, zorder=5))
ax.text(nx0, ny0 - h / 2 - 0.42, "The Nuclear Forge", fontsize=12, fontweight="bold",
        style="italic", color=TYRIAN_DARK, ha="center", va="center", zorder=6)

# ---------------------------------------------------------------- Customers: wax seals
names = [c["name"] for c in customers]
xs = [pos[n][0] for n in names]
ys = [pos[n][1] for n in names]

rings = ax.scatter(xs, ys, s=2900, c=[INK] * len(names), zorder=3)
cust_nodes = ax.scatter(xs, ys, s=2350, c=[LAPIS] * len(names),
                        edgecolors=GOLD, linewidths=2.2, zorder=4)
seal_labels = {}
for n, x, y in zip(names, xs, ys):
    seal_labels[n] = ax.text(x, y, n.replace("Customer ", "Customer\n"), fontsize=8,
                             fontweight="bold", color=PARCHMENT, ha="center",
                             va="center", zorder=6, linespacing=1.0)

price_annotations = {}

status_text = ax.text(
    0, -3.3, "The ledger is opened; each bid awaits its reckoning...",
    fontsize=12, style="italic", fontweight="bold", color=INK, ha="center", va="center", zorder=6,
    bbox=dict(boxstyle="round,pad=0.55", facecolor=PARCHMENT_2, edgecolor=INK, linewidth=1.6),
)


def set_colors(active_name=None, winner_name=None):
    cols = []
    for n in names:
        if winner_name and n == winner_name:
            cols.append(GOLD)
        elif active_name and n == active_name:
            cols.append(VERDIGRIS)
        else:
            cols.append(LAPIS)
    cust_nodes.set_facecolors(cols)
    for n in names:
        seal_labels[n].set_color(INK if n == winner_name else PARCHMENT)


def add_price_tag(name, price):
    x, y = pos[name]
    is_lowest = price == lowest_cust["price"]
    txt = ax.text(
        x + 0.62, y, f"${price:.1f} / MWh" + ("  (lowest)" if is_lowest else ""),
        fontsize=10.5, fontweight="bold", style="italic",
        color=TYRIAN_DARK if is_lowest else INK, ha="left", va="center", zorder=7,
        bbox=dict(boxstyle="round,pad=0.28",
                  facecolor="#f7e9a8" if is_lowest else PARCHMENT_2,
                  edgecolor=GOLD if is_lowest else SEPIA, linewidth=1.5),
    )
    price_annotations[name] = txt


def update(frame):
    if frame < len(customers):
        cust = customers[frame]
        set_colors(active_name=cust["name"])
        if cust["name"] not in price_annotations:
            add_price_tag(cust["name"], cust["price"])
        status_text.set_text(
            f"Weighing {cust['name']}'s bid:  ${cust['price']:.1f} per MWh ...")
    elif frame == len(customers):
        set_colors(winner_name=lowest_cust["name"])
        status_text.set_text(
            f"The reckoning is done!  {lowest_cust['name']} offers the lowest price: "
            f"${lowest_cust['price']:.1f} / MWh")
    else:
        # Pause frame, then restart cleanly on loop
        pass

    if frame == 0:
        for t in price_annotations.values():
            t.remove()
        price_annotations.clear()
        add_price_tag(customers[0]["name"], customers[0]["price"])

    return cust_nodes, status_text


ani = animation.FuncAnimation(fig, update, frames=len(customers) + 2,
                              interval=2000, blit=False, repeat=True)

if "--save" in sys.argv:
    for f in (2, len(customers)):
        for i in range(f + 1):
            update(i)
        fig.savefig(f"/home/claude/preview_{f}.png", dpi=110, facecolor=fig.get_facecolor())
else:
    plt.show()
