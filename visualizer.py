"""visualizer.py - interactive viewer for the UBT route search + Bayesian network.

Tabs
  (default map: data_ub/, 53 real Ulaanbaatar stations on the real road network,
   built by make_ub_graph.py from OpenStreetMap; --graph city/scale/osm for the others)
  Map & route      roads coloured by expected congestion, UCS / A* route, the
                   nodes each algorithm expanded. Left click = start, right
                   click = destination.
  Bayesian network the W, T -> C network with live probability bars (posterior
                   vs prior). Setting an observed congestion level shows
                   diagnostic reasoning: P(weather | congestion), P(time | ...).
  CPD table        all 9 rows of P(C | W, T) and a heatmap of P(high | W, T).
  Route details    the A* route with stop numbers and time since start, a
                   "how fast it got there" profile vs no conditions, minutes per
                   road; the methods used (pipeline). Click a road / bar / box
                   to see the calculation and the code of the method that did it.
  Step-by-step     UCS and A* side by side, one code line at a time: the real
                   search.py source with the running line highlighted, times
                   each line ran, queue, g / h / f. Play / step / speed.
  Checks           exact inference vs rejection sampling, sampling error vs n,
                   UCS == A* on random pairs with the current settings.

    python3 visualizer.py                          # window (needs tkinter)
    python3 visualizer.py --graph osm --weather snow --time "evening peak" --road-class
    python3 visualizer.py --snapshot out_dir       # save the 6 views as PNG, no window

If this Python has no tkinter (the pyenv build here), the window is reopened
with /usr/bin/python3 automatically. Offline, read-only: nothing is written
except --snapshot PNGs.
"""
import argparse
import math
import os
import random
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import matplotlib  # noqa: E402

from graph import Graph  # noqa: E402
from search import astar, ucs  # noqa: E402
import traffic as T  # noqa: E402

GRAPHS = {"ub": ("data_ub", "U01", "U33", "Ulaanbaatar stations (real map)"),
          "city": (".", "N01", "N15", "City (15 nodes, Week XII)"),
          "scale": ("data_scale", "S01", "S64", "Synthetic (64 nodes)"),
          "osm": ("data_osm", "N0674", "N1275", "OpenStreetMap UB (1852 nodes)")}
WEATHER_OPTS = ["(unknown)"] + T.WEATHER
TIME_OPTS = ["(unknown)"] + T.TIME
CONG_OPTS = ["(not observed)"] + T.LEVEL
PURPLE, GREY, RED, DARK, YELLOW = "#5b52a8", "#9aa2c0", "#e5473e", "#1a1f3d", "#f6e985"
COS_LAT = math.cos(math.radians(47.9))


# ============================================================ model side
class _Recorder:
    """Wraps a Graph and records which nodes the search expands (search.py
    calls neighbors() exactly once per expanded node, except the goal)."""

    def __init__(self, g):
        self._g, self.seen = g, []

    def __getattr__(self, k):
        return getattr(self._g, k)

    def neighbors(self, u):
        self.seen.append(u)
        return self._g.neighbors(u)


def run_search(fn, g, s, t, cost):
    rec = _Recorder(g)
    path, c, n = fn(rec, s, t, cost)
    expanded = rec.seen + ([t] if path else [])
    return dict(path=path, cost=c, expanded=n, expanded_nodes=expanded)


class Model:
    """Loads graphs once and caches conditioned copies."""

    def __init__(self):
        self.graphs, self.cond = {}, {}

    def graph(self, key):
        if key not in self.graphs:
            folder = os.path.join(HERE, GRAPHS[key][0])
            if key == "scale" and not os.path.exists(os.path.join(folder, "edges.csv")):
                import scale_test
                scale_test.generate(folder)
            g = Graph().load(os.path.join(folder, "nodes.csv"), os.path.join(folder, "edges.csv"))
            load_geometry(g, folder)
            self.graphs[key] = g
        return self.graphs[key]

    def conditioned(self, st):
        key = (st["graph"], st["weather"], st["time"], st["road_class"], st["expected_time"])
        if key not in self.cond:
            g = self.graph(st["graph"])
            if st["weather"] or st["time"]:
                g = T.apply_conditions(g, st["weather"], st["time"], by_class=st["road_class"],
                                       expected="time" if st["expected_time"] else "congestion")
            if len(self.cond) > 12:
                self.cond.clear()
            self.cond[key] = g
        return self.cond[key]

    def compute(self, st):
        g = self.conditioned(st)
        res = dict(g=g, base=self.graph(st["graph"]))
        res["ucs"] = run_search(ucs, g, st["src"], st["dst"], st["cost"])
        res["astar"] = run_search(astar, g, st["src"], st["dst"], st["cost"])
        res["p"] = T.congestion_dist(st["weather"], st["time"])
        return res


def load_geometry(g, folder):
    """Real street shapes (geometry.csv) and the full OSM road network as a
    background (data_osm_wide/) for the UB station graph. Stored as numpy
    arrays so the deep copies made by apply_conditions stay cheap."""
    import numpy as np
    geo_file = os.path.join(folder, "geometry.csv")
    if not os.path.exists(geo_file):
        return
    import csv
    g.geometry = {}
    with open(os.path.join(folder, "nodes.csv"), encoding="utf-8") as f:
        g.places = {r["id"]: (float(r["place_lon"]), float(r["place_lat"])) for r in csv.DictReader(f)
                    if r.get("place_lat")}
    with open(geo_file, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            pts = [tuple(map(float, p.split())) for p in r["points"].split(";")]
            g.geometry[(r["from"], r["to"])] = np.array([(lo, la) for la, lo in pts])
    roads = os.path.join(HERE, "data_osm_wide")
    if os.path.exists(os.path.join(roads, "edges.csv")):
        rn = {}
        with open(os.path.join(roads, "nodes.csv"), encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rn[r["id"]] = (float(r["lon"]), float(r["lat"]))
        with open(os.path.join(roads, "edges.csv"), encoding="utf-8") as f:
            g.basemap = np.array([(rn[r["from"]], rn[r["to"]]) for r in csv.DictReader(f)])


def default_state(graph="city"):
    _, s, t, _ = GRAPHS[graph]
    return dict(graph=graph, weather=None, time=None, congestion=None, road_class=False,
                expected_time=False, cost="time", src=s, dst=t, samples=2000)


def road_names(g, path):
    import re
    out = []
    for a, b in zip(path or [], (path or [])[1:]):
        r = next(e["road"] for e in g.adj[a] if e["dst"] == b)
        if re.match(r"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential)(_link)? \d+$", r):
            continue
        if not out or out[-1] != r:
            out.append(r)
    return out


def summary_text(st, res):
    g, U, A = res["g"], res["ucs"], res["astar"]
    unit = "min" if st["cost"] == "time" else "km"
    p = res["p"]
    name = lambda i: g.nodes[i][0]
    lines = [f"{GRAPHS[st['graph']][3]}",
             f"weather = {st['weather'] or 'unknown'}, time = {st['time'] or 'unknown'}",
             "P(congestion) low/med/high = " + " / ".join(f"{p[l]:.2f}" for l in T.LEVEL),
             f"model: {'road-class' if st['road_class'] else 'uniform'}"
             f"{', E[travel time]' if st['expected_time'] else ''}"
             + ("" if (st["weather"] or st["time"]) else "  (no conditions: edges.csv as is)"),
             "",
             f"{name(st['src'])}  ->  {name(st['dst'])}   (optimize {st['cost']})"]
    if A["path"] is None:
        lines.append("No route found.")
        return "\n".join(lines)
    same = abs(U["cost"] - A["cost"]) < 1e-9
    lines += [f"UCS : {U['cost']:.2f} {unit}, expanded {U['expanded']} nodes",
              f"A*  : {A['cost']:.2f} {unit}, expanded {A['expanded']} nodes",
              f"same optimal cost: {'YES' if same else 'NO  <-- check!'}"
              f" | A* saved {100 * (1 - A['expanded'] / max(U['expanded'], 1)):.0f}% of expansions",
              f"stops: {len(A['path'])}"]
    roads = road_names(g, A["path"])
    if roads:
        lines.append("roads: " + " -> ".join(roads[:8]) + (" ..." if len(roads) > 8 else ""))
    if len(A["path"]) <= 12:
        lines.append("route: " + " -> ".join(name(i) for i in A["path"]))
    return "\n".join(lines)


# ============================================================ drawing (Agg or Tk)
def draw_map(fig, st, res):
    from matplotlib.collections import LineCollection
    from viz_tabs import basemap, edge_poly, path_poly
    import matplotlib.cm as cm
    from matplotlib.colors import Normalize
    fig.clear()
    ax = fig.add_subplot(111)
    g = res["g"]
    basemap(ax, g)
    segs, vals = [], []
    for e in g.edges:
        segs.append(edge_poly(g, e["src"], e["dst"]))
        vals.append(e["congestion"])
    norm = Normalize(0, 0.95)
    cmap = matplotlib.colormaps["RdYlGn_r"]
    big = len(g.nodes) > 200
    lc = LineCollection(segs, colors=cmap(norm(vals)), linewidths=0.9 if big else 2.6, zorder=1, alpha=0.85)
    ax.add_collection(lc)
    U, A = res["ucs"], res["astar"]
    xy = lambda ids: ([g.nodes[i][2] for i in ids], [g.nodes[i][1] for i in ids])
    ax.scatter(*xy(U["expanded_nodes"]), s=10 if big else 140, color=GREY, alpha=0.55, zorder=2,
               label=f"UCS expanded ({U['expanded']})")
    ax.scatter(*xy(A["expanded_nodes"]), s=4 if big else 60, color=PURPLE, zorder=3,
               label=f"A* expanded ({A['expanded']})")
    if U["path"] and U["path"] != A["path"]:
        ax.plot(*path_poly(g, U["path"]).T, color=GREY, lw=3, ls="--", zorder=4, label="UCS route")
    if A["path"]:
        ax.plot(*path_poly(g, A["path"]).T, color=DARK, lw=3.2 if big else 4, zorder=5, label="A* route")
    s, t = g.nodes[st["src"]], g.nodes[st["dst"]]
    ax.scatter([s[2]], [s[1]], s=120, marker="o", color="#1f9d62", edgecolor="white", zorder=6, label="start")
    ax.scatter([t[2]], [t[1]], s=160, marker="*", color=RED, edgecolor="white", zorder=6, label="destination")
    if not big:
        from viz_tabs import draw_places, label_nodes
        draw_places(ax, g)
        small = len(g.nodes) <= 20
        label_nodes(ax, g, 7 if small or getattr(g, "places", None) else 6, 0.0 if small else 1.2,
                    names=small or bool(getattr(g, "places", None)), color=DARK)
    ax.autoscale()
    ax.set_aspect(1 / COS_LAT)
    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)
    sm = cm.ScalarMappable(norm=norm, cmap=cmap)
    fig.colorbar(sm, ax=ax, fraction=0.03, pad=0.01, label="expected congestion E[c] on the road")
    ax.legend(loc="lower right", fontsize=8, framealpha=0.85)
    cond = f"{st['weather'] or 'unknown weather'}, {st['time'] or 'unknown time'}" if (st["weather"] or st["time"]) \
        else "no conditions (edges.csv base congestion)"
    ax.set_title(f"{GRAPHS[st['graph']][3]} - {cond}"
                 + (" - road-class" if st["road_class"] and (st["weather"] or st["time"]) else ""), fontsize=11)
    if st["graph"] in ("osm", "ub"):
        ax.text(0.01, 0.01, "© OpenStreetMap contributors, ODbL", transform=ax.transAxes, ha="left",
                va="bottom", fontsize=7, color="#5d647d")
    fig.tight_layout()
    return ax


def bn_marginals(st):
    """Posterior of every variable given the evidence in st (observed ones are one-hot)."""
    ev = {k: st[k] for k in ("weather", "time", "congestion") if st[k]}
    out = {}
    for var, dom in (("weather", T.WEATHER), ("time", T.TIME), ("congestion", T.LEVEL)):
        if var in ev:
            out[var] = {v: 1.0 if v == ev[var] else 0.0 for v in dom}
        else:
            out[var] = T.posterior(var, {k: v for k, v in ev.items() if k != var})
    return out, ev


def draw_bn(fig, st):
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
    fig.clear()
    post, ev = bn_marginals(st)
    prior = {"weather": T.P_WEATHER, "time": T.P_TIME, "congestion": T.posterior("congestion", {})}
    boxes = {"weather": (0.04, 0.55, 0.32, 0.36, "Weather  W"),
             "time": (0.04, 0.08, 0.32, 0.36, "Time of day  T"),
             "congestion": (0.56, 0.31, 0.36, 0.38, "Congestion  C")}
    for var, (x, y, w, h, title) in boxes.items():
        observed = var in ev
        fig.patches.append(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.01,rounding_size=0.02",
                                          transform=fig.transFigure, facecolor=YELLOW if observed else "#f4f5fa",
                                          edgecolor=RED if var == "congestion" else PURPLE, lw=2, zorder=-5))
        fig.text(x + 0.015, y + h - 0.045, title + ("   (observed)" if observed else ""), fontsize=11,
                 weight="bold", color=DARK)
        ax = fig.add_axes([x + 0.11, y + 0.04, w - 0.15, h - 0.12])
        ax.set_zorder(5); ax.patch.set_alpha(0)
        dom = list(post[var])
        ys = range(len(dom))[::-1]
        ax.barh(list(ys), [prior[var][d] for d in dom], color="none", edgecolor=GREY, lw=1.2, height=0.7,
                label="prior")
        ax.barh(list(ys), [post[var][d] for d in dom], color=RED if observed else PURPLE, alpha=0.85, height=0.45,
                label="posterior")
        for yy, d in zip(ys, dom):
            ax.text(min(post[var][d], 0.82) + 0.02, yy, f"{post[var][d]:.3f}", va="center", fontsize=9, color=DARK)
        ax.set_yticks(list(ys)); ax.set_yticklabels(dom, fontsize=9)
        ax.set_xlim(0, 1); ax.tick_params(axis="x", labelsize=7)
        ax.spines[["top", "right"]].set_visible(False)
        if var == "congestion":
            ax.legend(fontsize=7, loc="lower left", bbox_to_anchor=(0.0, 1.0), ncol=2, frameon=False)
    for (x0, y0), (x1, y1) in [((0.36, 0.73), (0.56, 0.55)), ((0.36, 0.26), (0.56, 0.45))]:
        fig.patches.append(FancyArrowPatch((x0, y0), (x1, y1), transform=fig.transFigure, arrowstyle="-|>",
                                           mutation_scale=22, lw=2, color=DARK))
    # what is being computed, in words
    q = []
    if "congestion" in ev:
        q.append(f"Diagnostic: P(W | C={ev['congestion']}) and P(T | C={ev['congestion']}) by Bayes rule")
    rest = {k: v for k, v in ev.items() if k != "congestion"}
    if "congestion" not in ev:
        q.append("Predictive: P(C | " + (", ".join(f"{k[0].upper()}={v}" for k, v in rest.items()) or "nothing observed")
                 + ")" + ("" if len(rest) == 2 else "   (unobserved parents summed out with their prior)"))
    e_lvl = sum(post["congestion"][l] * T.LEVEL_VALUE[l] for l in T.LEVEL)
    q.append(f"Expected city congestion level = {e_lvl:.3f}   |   exact inference: enumeration of 27 joint entries")
    fig.text(0.04, 0.965, "Bayesian network  P(W,T,C) = P(W) P(T) P(C | W,T)", fontsize=13, weight="bold", color=DARK)
    fig.text(0.56, 0.20, "\n".join(q), fontsize=9, color=DARK, va="top", wrap=True)
    fig.text(0.56, 0.80, "Grey outline = prior (nothing observed)\nFilled bar = posterior with the current evidence",
             fontsize=8.5, color="#5d647d", va="top")


def draw_cpd(fig, st):
    fig.clear()
    ax1 = fig.add_axes([0.2, 0.12, 0.38, 0.78])
    rows = [(w, t) for w in T.WEATHER for t in T.TIME]
    cols = {"low": "#1f9d62", "medium": "#f2c14e", "high": RED}
    ys = list(range(len(rows)))[::-1]
    left = [0.0] * len(rows)
    for i, l in enumerate(T.LEVEL):
        vals = [T.CPD_CONG[r][i] for r in rows]
        ax1.barh(ys, vals, left=left, color=cols[l], label=l, height=0.7)
        for y, v, lf in zip(ys, vals, left):
            if v >= 0.08:
                ax1.text(lf + v / 2, y, f"{v:.2f}", ha="center", va="center", fontsize=8, color=DARK)
        left = [a + b for a, b in zip(left, vals)]
    ax1.set_yticks(ys)
    labels = [f"{w} + {t.replace('_', ' ')}" for w, t in rows]
    ax1.set_yticklabels(labels, fontsize=9)
    for y, r, tl in zip(ys, rows, ax1.get_yticklabels()):
        sel = (st["weather"] in (None, r[0])) and (st["time"] in (None, r[1])) and (st["weather"] or st["time"])
        if sel:
            tl.set_color(RED); tl.set_fontweight("bold")
        s = sum(T.CPD_CONG[r])
        ax1.text(1.02, y, "Σ=1 ✓" if abs(s - 1) < 1e-9 else f"Σ={s:.3f} ✗", va="center", fontsize=8,
                 color="#1f9d62" if abs(s - 1) < 1e-9 else RED)
    ax1.set_xlim(0, 1.13); ax1.set_xlabel("P(congestion level | W, T)")
    ax1.set_title("CPD rows (selected evidence in red)", fontsize=11)
    ax1.legend(ncol=3, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.07), frameon=False)
    ax1.spines[["top", "right"]].set_visible(False)

    ax2 = fig.add_axes([0.66, 0.42, 0.3, 0.45])
    grid = [[T.CPD_CONG[(w, t)][2] for t in T.TIME] for w in T.WEATHER]
    im = ax2.imshow(grid, cmap="Reds", vmin=0, vmax=1)
    for i in range(3):
        for j in range(3):
            ax2.text(j, i, f"{grid[i][j]:.2f}", ha="center", va="center", fontsize=10,
                     color="white" if grid[i][j] > 0.5 else DARK)
    ax2.set_xticks(range(3)); ax2.set_xticklabels([t.replace("_", "\n") for t in T.TIME], fontsize=8)
    ax2.set_yticks(range(3)); ax2.set_yticklabels(T.WEATHER, fontsize=9)
    ax2.set_title("P(high | W, T)", fontsize=11)
    fig.colorbar(im, ax=ax2, fraction=0.046)
    pri = ("Priors\n  P(W): " + ", ".join(f"{k} {v:.2f}" for k, v in T.P_WEATHER.items())
           + "\n  P(T): " + "\n        ".join(f"{k.replace('_', ' ')} {v:.2f}" for k, v in T.P_TIME.items())
           + "\nRoad-class k: " + ", ".join(f"{k} {v}" for k, v in T.ROAD_CLASS_K.items())
           + "\nLevel shift Δ: " + ", ".join(f"{k} {v:+.2f}" for k, v in T.SHIFT.items()))
    fig.text(0.64, 0.33, pri, fontsize=8, color=DARK, va="top", family="monospace")


DOMAINS = {"weather": T.WEATHER, "time": T.TIME, "congestion": T.LEVEL}


def query_of(st):
    """What the Checks tab verifies: P(C | W, T) normally; with an observed
    congestion level the diagnostic query P(W | C, ...)."""
    ev = {k: st[k] for k in ("weather", "time", "congestion") if st[k]}
    if "congestion" in ev:
        for q in ("weather", "time"):
            if q not in ev:
                return q, ev
        ev.pop("congestion")  # W and T both observed: nothing to infer backwards
    return "congestion", ev


def sample_dist(query, ev, n, rng):
    """Monte Carlo estimate of P(query | ev) by forward sampling.
    Evidence on the root nodes W, T is clamped (all samples get the same
    weight P(w) P(t), so this equals rejection sampling, just faster);
    evidence on C is handled by rejection."""
    wv, tv = [T.P_WEATHER[x] for x in T.WEATHER], [T.P_TIME[x] for x in T.TIME]
    counts, kept, tries = {v: 0 for v in DOMAINS[query]}, 0, 0
    while kept < n:
        tries += 1
        if tries > 200 * n:
            raise ValueError("evidence too unlikely for sampling")
        w = ev.get("weather") or rng.choices(T.WEATHER, wv)[0]
        t = ev.get("time") or rng.choices(T.TIME, tv)[0]
        c = rng.choices(T.LEVEL, T.CPD_CONG[(w, t)])[0]
        if ev.get("congestion") not in (None, c):
            continue
        counts[{"weather": w, "time": t, "congestion": c}[query]] += 1
        kept += 1
    return {v: counts[v] / n for v in DOMAINS[query]}


def checks(model, st, pairs=150, seed=1):
    """Numbers for the Checks tab (also used by the tests)."""
    rng = random.Random(seed)
    query, ev = query_of(st)
    exact = T.posterior(query, ev)
    sampled = sample_dist(query, ev, st["samples"], rng)
    ns = [100, 300, 1000, 3000, 10000]
    runs = 8
    err = [sum(max(abs(a - exact[v]) for v, a in sample_dist(query, ev, n, rng).items()) for _ in range(runs)) / runs
           for n in ns]
    g = model.conditioned(st)
    ids = list(g.nodes)
    prs = set()
    while len(prs) < min(pairs, len(ids) * (len(ids) - 1)):
        prs.add(tuple(rng.sample(ids, 2)))
    nu, na, bad = [], [], 0
    for s, d in sorted(prs):
        pu, cu, xu = ucs(g, s, d, st["cost"])
        pa, ca, xa = astar(g, s, d, st["cost"])
        nu.append(xu); na.append(xa)
        bad += (pu is None) != (pa is None) or abs(cu - ca) > 1e-9
    sums_ok = all(abs(sum(r) - 1) < 1e-9 for r in T.CPD_CONG.values())
    return dict(query=query, ev=ev, exact=exact, sampled=sampled, ns=ns, err=err, runs=runs,
                nu=nu, na=na, bad=bad, pairs=len(prs), sums_ok=sums_ok)


def draw_checks(fig, model, st, ck=None):
    ck = ck or checks(model, st)
    fig.clear()
    ax = fig.subplots(2, 2)
    dom = DOMAINS[ck["query"]]
    x = range(len(dom))
    a = ax[0][0]
    a.bar([i - 0.2 for i in x], [ck["exact"][v] for v in dom], 0.4, color=PURPLE, label="exact (enumeration)")
    a.bar([i + 0.2 for i in x], [ck["sampled"][v] for v in dom], 0.4, color=GREY,
          label=f"sampling n={st['samples']}")
    for i, v in enumerate(dom):
        a.text(i - 0.2, ck["exact"][v] + 0.01, f"{ck['exact'][v]:.3f}", ha="center", fontsize=8)
        a.text(i + 0.2, ck["sampled"][v] + 0.01, f"{ck['sampled'][v]:.3f}", ha="center", fontsize=8)
    a.set_xticks(list(x)); a.set_xticklabels(dom)
    ev = ", ".join(f"{k[0].upper()}={v}" for k, v in ck["ev"].items()) or "no evidence"
    kind = "diagnostic" if "congestion" in ck["ev"] else "predictive"
    a.set_title(f"{kind}: P({ck['query'][0].upper()} | {ev}) exact vs sampling", fontsize=10)
    a.legend(fontsize=7, frameon=False); a.set_ylim(0, 1)
    a = ax[0][1]
    err = [max(e, 1e-6) for e in ck["err"]]
    a.loglog(ck["ns"], err, "o-", color=PURPLE, label=f"mean max|error|, {ck['runs']} runs")
    a.loglog(ck["ns"], [err[0] * math.sqrt(ck["ns"][0] / n) for n in ck["ns"]], "--", color=GREY,
             label="1/√n reference")
    a.set_xlabel("samples n"); a.set_title("Sampling error shrinks like 1/√n (exact = 0 error)", fontsize=10)
    a.legend(fontsize=7, frameon=False)
    a = ax[1][0]
    a.scatter(ck["nu"], ck["na"], s=10, color=PURPLE, alpha=0.6)
    m = max(ck["nu"] + ck["na"] + [1])
    a.plot([0, m], [0, m], "--", color=GREY, lw=1)
    a.set_xlabel("UCS nodes expanded"); a.set_ylabel("A* nodes expanded")
    red = 100 * (1 - sum(ck["na"]) / max(sum(ck["nu"]), 1))
    a.set_title(f"{ck['pairs']} random pairs: A* expands {red:.0f}% fewer", fontsize=10)
    a = ax[1][1]
    a.axis("off")
    ok = ck["bad"] == 0 and ck["sums_ok"] and max(abs(ck["exact"][v] - ck["sampled"][v]) for v in dom) < 0.05
    lines = [f"CPD rows sum to 1 ........ {'PASS' if ck['sums_ok'] else 'FAIL'}",
             f"sampling within 0.05 ...... {'PASS' if max(abs(ck['exact'][v] - ck['sampled'][v]) for v in dom) < 0.05 else 'FAIL'}",
             f"UCS == A* optimal cost .... {'PASS' if ck['bad'] == 0 else 'FAIL'} "
             f"({ck['pairs'] - ck['bad']}/{ck['pairs']} pairs, cost={st['cost']})",
             f"max |exact - sampled| ..... {max(abs(ck['exact'][v] - ck['sampled'][v]) for v in dom):.4f}",
             "",
             "Settings: " + GRAPHS[st["graph"]][3],
             f"  weather={st['weather'] or '-'}, time={st['time'] or '-'}",
             f"  road-class={'on' if st['road_class'] else 'off'}, E[t]={'on' if st['expected_time'] else 'off'}"]
    a.text(0, 1, "\n".join(lines), va="top", family="monospace", fontsize=9, color=DARK)
    a.text(0, 0.05, "ALL CHECKS PASS" if ok else "SOME CHECKS FAIL", fontsize=14, weight="bold",
           color="#1f9d62" if ok else RED)
    fig.tight_layout()
    return ck


def snapshot(st, out_dir):
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    os.makedirs(out_dir, exist_ok=True)
    import viz_tabs
    import viz_trace
    model = Model()
    res = model.compute(st)
    segs = viz_trace.route_segments(res["g"], res["base"], res["astar"]["path"]) if res["astar"]["path"] else []
    sel = viz_tabs.default_selected(segs)
    files = []
    for name, fn in [("map", lambda f: draw_map(f, st, res)),
                     ("route", lambda f: viz_tabs.draw_route(f, st, res, segs, sel)),
                     ("steps", lambda f: viz_tabs.draw_trace_final(f, res["g"], st, st["cost"])),
                     ("bayes_net", lambda f: draw_bn(f, st)),
                     ("cpd", lambda f: draw_cpd(f, st)), ("checks", lambda f: draw_checks(f, model, st))]:
        fig = plt.figure(figsize=(12, 7.5) if name == "route" else (11, 6.5), dpi=110)
        fn(fig)
        p = os.path.join(out_dir, f"viz_{name}.png")
        fig.savefig(p)
        plt.close(fig)
        files.append(p)
    print(summary_text(st, res))
    if segs:
        print("\nSlowest segment explained (as in the Route details tab):")
        print(viz_trace.explain_edge(segs[sel - 1], st)[0])
    print("\nsaved: " + ", ".join(files))
    return files


# ============================================================ window (tkinter)
class App:
    def __init__(self, root, st):
        import tkinter as tk
        from tkinter import ttk
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
        from matplotlib.figure import Figure
        self.tk, self.ttk = tk, ttk
        self.root, self.st, self.model = root, st, Model()
        root.title("UBT route search - visualizer")
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{min(1500, sw - 40)}x{min(900, sh - 80)}+10+10")
        try:
            root.attributes("-zoomed", True)  # maximise (Linux / Windows)
        except Exception:
            pass

        side = ttk.Frame(root, padding=8)
        side.pack(side="left", fill="y")
        self.vars = {}

        def combo(label, key, values, width=22):
            ttk.Label(side, text=label).pack(anchor="w", pady=(6, 0))
            v = tk.StringVar()
            cb = ttk.Combobox(side, textvariable=v, values=values, state="readonly", width=width)
            cb.pack(anchor="w", fill="x")
            cb.bind("<<ComboboxSelected>>", lambda _e: self.on_change(key))
            self.vars[key] = (v, cb)
            return v, cb

        combo("Graph", "graph", list(GRAPHS))
        combo("Weather (evidence)", "weather", WEATHER_OPTS)
        combo("Time of day (evidence)", "time", TIME_OPTS)
        combo("Observed congestion (BN tab only)", "congestion", CONG_OPTS)
        combo("Optimize", "cost", ["time", "dist"])
        self.bools = {}
        for key, label in (("road_class", "Road-class model (--road-class)"),
                           ("expected_time", "Expected travel time (--expected-time)")):
            b = tk.BooleanVar(value=st[key])
            ttk.Checkbutton(side, text=label, variable=b, command=lambda k=key: self.on_change(k)).pack(anchor="w", pady=2)
            self.bools[key] = b
        combo("From (or left-click map)", "src", [], 34)
        combo("To (or right-click map)", "dst", [], 34)
        ttk.Label(side, text="Samples for the Checks tab").pack(anchor="w", pady=(6, 0))
        self.samples = tk.IntVar(value=st["samples"])
        ttk.Spinbox(side, from_=100, to=50000, increment=500, textvariable=self.samples, width=10,
                    command=lambda: self.on_change("samples")).pack(anchor="w")
        ttk.Button(side, text="Swap from/to", command=self.swap).pack(anchor="w", fill="x", pady=(8, 2))
        ttk.Button(side, text="Reset evidence", command=self.reset).pack(anchor="w", fill="x")
        self.info = tk.Text(side, width=46, height=18, wrap="word", font=("monospace", 9))
        self.info.pack(anchor="w", fill="both", expand=True, pady=(10, 0))

        nb = ttk.Notebook(root)
        nb.pack(side="right", fill="both", expand=True)
        self.figs, self.canvases = {}, {}
        for name in ("Map & route", "Bayesian network", "CPD table", "Checks"):
            frame = ttk.Frame(nb)
            nb.add(frame, text=name)
            fig = Figure(figsize=(10, 7), dpi=100)
            canvas = FigureCanvasTkAgg(fig, master=frame)
            if name == "Map & route":
                NavigationToolbar2Tk(canvas, frame).update()
                canvas.mpl_connect("button_press_event", self.on_click)
            canvas.get_tk_widget().pack(fill="both", expand=True)
            self.figs[name], self.canvases[name] = fig, canvas
        self.nb = nb
        import viz_tabs
        self.route_tab = viz_tabs.RouteTab(nb, self)
        self.step_tab = viz_tabs.StepTab(nb, self)
        nb.insert(1, self.route_tab.frame)
        nb.insert(2, self.step_tab.frame)
        nb.bind("<<NotebookTabChanged>>", lambda _e: self.redraw(only_visible=True))
        self.sync_widgets()
        self.redraw()

    # ---- state <-> widgets
    def node_label(self, g, i):
        return f"{i}  {g.nodes[i][0]}"

    def sync_widgets(self):
        st = self.st
        g = self.model.graph(st["graph"])
        labels = [self.node_label(g, i) for i in g.nodes]
        for key in ("src", "dst"):
            self.vars[key][1]["values"] = labels
            self.vars[key][0].set(self.node_label(g, st[key]))
        self.vars["graph"][0].set(st["graph"])
        self.vars["weather"][0].set(st["weather"] or WEATHER_OPTS[0])
        self.vars["time"][0].set(st["time"] or TIME_OPTS[0])
        self.vars["congestion"][0].set(st["congestion"] or CONG_OPTS[0])
        self.vars["cost"][0].set(st["cost"])
        for k, b in self.bools.items():
            b.set(st[k])

    def on_change(self, key):
        st = self.st
        if key == "graph":
            new = self.vars["graph"][0].get()
            if new != st["graph"]:
                keep = {k: st[k] for k in ("weather", "time", "congestion", "road_class", "expected_time", "cost", "samples")}
                self.st = st = dict(default_state(new), **keep)
                self.root.config(cursor="watch"); self.root.update()
                self.sync_widgets()
                self.root.config(cursor="")
        elif key in ("weather", "time", "congestion"):
            v = self.vars[key][0].get()
            st[key] = None if v.startswith("(") else v
        elif key in ("src", "dst"):
            st[key] = self.vars[key][0].get().split()[0]
        elif key == "cost":
            st["cost"] = self.vars["cost"][0].get()
        elif key in self.bools:
            st[key] = self.bools[key].get()
        elif key == "samples":
            try:
                st["samples"] = max(100, int(self.samples.get()))
            except (ValueError, self.tk.TclError):
                return
        self.redraw()

    def swap(self):
        self.st["src"], self.st["dst"] = self.st["dst"], self.st["src"]
        self.sync_widgets(); self.redraw()

    def reset(self):
        for k in ("weather", "time", "congestion"):
            self.st[k] = None
        self.st["road_class"] = self.st["expected_time"] = False
        self.sync_widgets(); self.redraw()

    def on_click(self, ev):
        if ev.inaxes is None or ev.xdata is None or ev.button not in (1, 3):
            return
        if self.canvases["Map & route"].toolbar.mode:  # zoom / pan active
            return
        g = self.model.graph(self.st["graph"])
        best = min(g.nodes, key=lambda i: ((g.nodes[i][2] - ev.xdata) * COS_LAT) ** 2 + (g.nodes[i][1] - ev.ydata) ** 2)
        self.st["src" if ev.button == 1 else "dst"] = best
        self.sync_widgets(); self.redraw()

    # ---- drawing
    def redraw(self, only_visible=False):
        st = self.st
        if st["src"] == st["dst"]:
            self.info.delete("1.0", "end"); self.info.insert("end", "Pick two different places.")
            return
        self.root.config(cursor="watch"); self.root.update_idletasks()
        try:
            res = self.model.compute(st)
            self.info.delete("1.0", "end")
            self.info.insert("end", summary_text(st, res))
            current = self.nb.tab(self.nb.select(), "text")
            for name, fn in (("Map & route", lambda f: draw_map(f, st, res)), ("Bayesian network", lambda f: draw_bn(f, st)),
                             ("CPD table", lambda f: draw_cpd(f, st)),
                             ("Checks", lambda f: draw_checks(f, self.model, st))):
                if only_visible and name != current:
                    continue
                if name == "Checks" and name != current:
                    self.figs[name].clear(); self.canvases[name].draw_idle()
                    continue  # expensive: only when visible
                fn(self.figs[name])
                self.canvases[name].draw_idle()
            if current == "Route details":
                self.route_tab.refresh(st, res)
            elif current == "Step-by-step (code)":
                self.step_tab.refresh(st, res)
            else:
                self.step_tab.playing = False
        finally:
            self.root.config(cursor="")


# ============================================================ entry point
def has_tk():
    try:
        import tkinter  # noqa: F401
        return True
    except ImportError:
        return False


def main():
    ap = argparse.ArgumentParser(description="UBT route search + Bayesian network visualizer")
    ap.add_argument("--graph", choices=list(GRAPHS), default="ub")
    ap.add_argument("--weather")
    ap.add_argument("--time", nargs="+")
    ap.add_argument("--congestion", choices=T.LEVEL, help="observed congestion (Bayesian network tab)")
    ap.add_argument("--road-class", action="store_true")
    ap.add_argument("--expected-time", action="store_true")
    ap.add_argument("--cost", choices=["time", "dist"], default="time")
    ap.add_argument("--from", dest="src")
    ap.add_argument("--to", dest="dst")
    ap.add_argument("--samples", type=int, default=2000)
    ap.add_argument("--snapshot", metavar="DIR", help="save the 4 tabs as PNG and exit (no window)")
    a = ap.parse_args()
    st = default_state(a.graph)
    try:
        st.update(weather=T.normalize(a.weather, T.WEATHER), time=T.normalize(" ".join(a.time), T.TIME) if a.time else None)
    except ValueError as err:
        ap.error(str(err))
    st.update(congestion=a.congestion, road_class=a.road_class, expected_time=a.expected_time, cost=a.cost,
              samples=max(100, a.samples))
    g = Model().graph(a.graph)
    for k in ("src", "dst"):
        v = getattr(a, k)
        if v:
            if v not in g.nodes:
                ap.error(f"unknown node {v} in graph {a.graph}")
            st[k] = v
    if a.snapshot:
        return snapshot(st, a.snapshot)
    if not has_tk():
        alt = "/usr/bin/python3"
        if os.path.exists(alt) and os.path.realpath(alt) != os.path.realpath(sys.executable) and \
                subprocess.run([alt, "-c", "import tkinter, matplotlib"], capture_output=True).returncode == 0:
            print(f"This Python ({sys.executable}) has no tkinter; opening the window with {alt} ...", flush=True)
            os.execv(alt, [alt, os.path.abspath(__file__)] + sys.argv[1:])
        sys.exit("No tkinter in this Python. Use a Python with tkinter, or --snapshot DIR for PNG output.")
    matplotlib.use("TkAgg")
    import tkinter as tk
    root = tk.Tk()
    App(root, st)
    root.mainloop()


if __name__ == "__main__":
    main()
