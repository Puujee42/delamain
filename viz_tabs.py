"""viz_tabs.py - the "Step-by-step (code)" and "Route details" tabs of visualizer.py.

Drawing is plain matplotlib (works headless for --snapshot and the tests);
the tkinter parts (StepTab, RouteTab) are only used by the window.
"""
import math

import matplotlib
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.colors import Normalize
from matplotlib.patches import FancyBboxPatch

import traffic as T
import viz_trace as VT

COS_LAT = math.cos(math.radians(47.9))
ALGOS = ("ucs", "astar")
ALGO_COLOR = {"ucs": "#7d86ad", "astar": "#5b52a8"}
ALGO_LIGHT = {"ucs": "#dfe3f2", "astar": "#ddd6ff"}
ALGO_NAME = {"ucs": "UCS", "astar": "A*"}
SHORT_EVENT = {"init": "start", "pop": "pop", "skip": "skip stale", "expand": "expand", "goal": "goal reached",
               "relax": "check road", "test": "compare cost", "push": "push", "fail": "no route"}
FRONTIER, RELAX, DARK, RED, GREEN = "#f2a541", "#e5473e", "#1a1f3d", "#e5473e", "#1f9d62"
CMAP = matplotlib.colormaps["RdYlGn_r"]
NORM = Normalize(0, 0.95)
# the lines that matter in each method (highlighted in the code view)
KEY_LINES = {
    "Graph.load": ["dist = haversine_km(la, lo, lb, lob) * DETOUR_FACTOR", '"time_min": self.round_time'],
    "traffic.congestion_dist": ["return posterior("],
    "traffic.edge_congestion": ["return min(C_MAX"],
    "traffic.expected_edge_congestion": ["return sum("],
    "traffic.expected_edge_time": ["return sum("],
    "traffic.apply_conditions": ["ke = ", "c = expected_edge_congestion", "t = (expected_edge_time"],
    "Graph.travel_time_min": ["eff = ", "return dist_km"],
    "search.ucs": ["heapq.heappop", "heapq.heappush"],
    "search.astar": ["return g.heuristic_time_min", "heapq.heappop", "heapq.heappush"],
}


def _xy(g, ids):
    ids = list(ids)
    if not ids:
        return np.empty((0, 2))
    return np.array([(g.nodes[i][2], g.nodes[i][1]) for i in ids])


def _segments(g):
    return [[(g.nodes[e["src"]][2], g.nodes[e["src"]][1]), (g.nodes[e["dst"]][2], g.nodes[e["dst"]][1])] for e in g.edges]


def _plain(ax):
    ax.set_aspect(1 / COS_LAT)
    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)


# ===================================================================== step view
class StepView:
    """Two maps (UCS | A*) whose artists are updated in place while the trace runs."""

    def __init__(self, fig, g, st):
        fig.clear()
        self.fig, self.g, self.art = fig, g, {}
        big = len(g.nodes) > 200
        segs = _segments(g)
        names = len(g.nodes) <= 20
        for i, algo in enumerate(ALGOS):
            ax = fig.add_subplot(1, 2, i + 1)
            ax.add_collection(LineCollection(segs, colors="#d5d8e6", linewidths=0.6 if big else 2.2, zorder=1))
            if not big:
                ax.scatter(*_xy(g, g.nodes).T, s=28, color="#c9cde0", zorder=2)
            a = dict(ax=ax)
            a["done"] = ax.scatter([], [], s=8 if big else 150, color=ALGO_COLOR[algo], zorder=3,
                                   label="expanded (done)")
            a["front"] = ax.scatter([], [], s=8 if big else 110, color=FRONTIER, edgecolor="#b5651d", zorder=4,
                                    label="waiting in the queue")
            a["relax"], = ax.plot([], [], color=RELAX, lw=2.5 if big else 4, zorder=5, label="road being checked")
            a["cur"] = ax.scatter([], [], s=60 if big else 420, facecolor="none", edgecolor=DARK, lw=2.5, zorder=6,
                                  label="current node")
            a["path"], = ax.plot([], [], color=DARK, lw=3 if big else 5, zorder=7, label="final path")
            s, t = g.nodes[st["src"]], g.nodes[st["dst"]]
            ax.scatter([s[2]], [s[1]], s=140, color=GREEN, edgecolor="white", zorder=8)
            ax.scatter([t[2]], [t[1]], s=200, marker="*", color=RED, edgecolor="white", zorder=8)
            if not big:
                for n, (nm, la, lo) in g.nodes.items():
                    ax.annotate(nm if names else n, (lo, la), fontsize=6.5, xytext=(5, 5), textcoords="offset points",
                                color="#5d647d", zorder=9)
            ax.autoscale()
            _plain(ax)
            a["title"] = ax.set_title(ALGO_NAME[algo], fontsize=11, color=ALGO_COLOR[algo], weight="bold")
            if i == 1:
                ax.legend(loc="lower right", fontsize=7, framealpha=0.9)
            self.art[algo] = a
        fig.tight_layout()

    def update(self, algo, s):
        a, g = self.art[algo], self.g
        a["done"].set_offsets(_xy(g, s.done))
        live = {e[-1] for e in s.pq} - s.done
        a["front"].set_offsets(_xy(g, live))
        a["cur"].set_offsets(_xy(g, [s.u] if s.u and not s.finished else []))
        if s.event in ("relax", "test", "push") and s.v is not None:
            (x0, y0), (x1, y1) = _xy(g, [s.u, s.v])
            a["relax"].set_data([x0, x1], [y0, y1])
        else:
            a["relax"].set_data([], [])
        if s.path:
            p = _xy(g, s.path)
            a["path"].set_data(p[:, 0], p[:, 1])
        else:
            a["path"].set_data([], [])
        state = (f"DONE: cost {s.cost:.2f}" if s.finished and s.path else "no route" if s.finished else
                 SHORT_EVENT.get(s.event, "") + (f" {s.u}" if s.event in ("pop", "expand", "skip") else
                                                 f" {s.u}->{s.v}" if s.v is not None and s.event in ("relax", "test", "push") else ""))
        a["title"].set_text(f"{ALGO_NAME[algo]}  |  step {s.steps}  |  expanded {s.expanded}  |  queue {len(live)}"
                            f"\n{state}")


def draw_trace_final(fig, g, st, cost="time"):
    """Static version for --snapshot: both algorithms run to the end."""
    view = StepView(fig, g, st)
    states = {}
    for algo in ALGOS:
        states[algo] = VT.run_trace(g, st["src"], st["dst"], cost, algo)
        view.update(algo, states[algo])
    return states


# ===================================================================== route view
def _pipeline(ax, st, selected_method=None):
    boxes = VT.pipeline(st)
    ax.set_xlim(-0.1, len(boxes) - 0.1); ax.set_ylim(0, 1); ax.axis("off")
    for i, (label, method, active, col) in enumerate(boxes):
        sel = method == selected_method
        p = FancyBboxPatch((i + 0.04, 0.12), 0.78, 0.76, boxstyle="round,pad=0.02,rounding_size=0.08",
                           facecolor=col if active else "#f0f1f6", edgecolor=DARK if sel else (col if active else "#c9cde0"),
                           lw=3 if sel else 1.2, ls="-" if active else "--", picker=True, zorder=2)
        p.set_gid(f"method:{method}")
        ax.add_patch(p)
        ax.text(i + 0.43, 0.5, label, ha="center", va="center", fontsize=8, color="white" if active else "#9aa2c0",
                weight="bold" if active else "normal", zorder=3)
        if i < len(boxes) - 1:
            ax.annotate("", (i + 1.03, 0.5), (i + 0.83, 0.5), arrowprops=dict(arrowstyle="->", color="#9aa2c0", lw=1.2))
    ax.set_title("Methods used (coloured = used now, dashed = off). Click a box to see its code.", fontsize=9,
                 color="#5d647d", loc="left")


def draw_route(fig, st, res, segs, selected=None, method=None):
    """Route map, speed profile and per-segment bars. Artists that can be clicked
    carry gid 'seg:<i>' or 'method:<name>'."""
    fig.clear()
    g = res["g"]
    path = res["astar"]["path"]
    gs = fig.add_gridspec(3, 2, height_ratios=[0.55, 3.0, 1.45], width_ratios=[1.3, 1], hspace=0.38, wspace=0.12)
    _pipeline(fig.add_subplot(gs[0, :]), st, method)
    if not path or not segs:
        fig.text(0.5, 0.5, "No route", ha="center", fontsize=14)
        return
    total, km = segs[-1]["cum_min"], segs[-1]["cum_km"]
    base_total = segs[-1]["cum_base"]

    # ---- route map
    ax = fig.add_subplot(gs[1, 0])
    pts = _xy(g, path)
    (x0, y0), (x1, y1) = pts.min(0), pts.max(0)
    pad = max(x1 - x0, (y1 - y0) / COS_LAT, 0.01) * 0.12
    ax.add_collection(LineCollection(_segments(g), colors="#e1e3ec", linewidths=1.2, zorder=1))
    for s_ in segs:
        (ax_, ay), (bx, by) = _xy(g, [s_["a"], s_["b"]])
        sel = selected == s_["i"]
        if sel:
            ax.plot([ax_, bx], [ay, by], color=DARK, lw=12, zorder=2, solid_capstyle="round")
        ln, = ax.plot([ax_, bx], [ay, by], color=CMAP(NORM(s_["c"])), lw=7, zorder=3, solid_capstyle="round", picker=6)
        ln.set_gid(f"seg:{s_['i']}")
        mx, my, dx, dy = (ax_ + bx) / 2, (ay + by) / 2, (bx - ax_) * 0.04, (by - ay) * 0.04
        ax.annotate("", (mx + dx, my + dy), (mx - dx, my - dy),
                    arrowprops=dict(arrowstyle="-|>", color=DARK, lw=0, mutation_scale=16), zorder=4)
    n = len(path)
    cum = [0.0] + [s_["cum_min"] for s_ in segs]
    ckm = [0.0] + [s_["cum_km"] for s_ in segs]
    gap, last = km / 12 if n > 14 else -1, None   # label stops spread along the route
    for k, (node, (x, y)) in enumerate(zip(path, pts)):
        far_enough = last is None or ckm[k] - ckm[last] >= gap
        near_end = 0 < ckm[-1] - ckm[k] < gap and k != n - 1
        if not far_enough or near_end:
            continue
        last = k
        ax.scatter([x], [y], s=190, color="white", edgecolor=DARK, zorder=5)
        ax.text(x, y, str(k), ha="center", va="center", fontsize=7, weight="bold", zorder=6)
        ax.annotate(f"{cum[k]:.1f} min", (x, y), xytext=(8, -12), textcoords="offset points", fontsize=7,
                    color=DARK, zorder=6, bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.8))
    ax.scatter([pts[0][0]], [pts[0][1]], s=260, color=GREEN, zorder=4)
    ax.scatter([pts[-1][0]], [pts[-1][1]], s=330, marker="*", color=RED, zorder=7)
    ax.set_xlim(x0 - pad, x1 + pad); ax.set_ylim(y0 - pad * COS_LAT, y1 + pad * COS_LAT)
    _plain(ax)
    sm = matplotlib.cm.ScalarMappable(norm=NORM, cmap=CMAP)
    cax = ax.inset_axes([0.03, 0.04, 0.32, 0.03])
    cb = fig.colorbar(sm, cax=cax, orientation="horizontal")
    cb.set_label("road colour = E[congestion]", fontsize=7); cb.ax.tick_params(labelsize=6)
    avg = km / (total / 60) if total > 0 and st["cost"] == "time" else 0
    unit = "min" if st["cost"] == "time" else "km"
    ax.set_title(f"A* route: {total:.2f} {unit}, {km:.2f} km, {len(segs)} roads"
                 + (f", avg {avg:.0f} km/h" if avg else "") + "\n(numbers = stop, label = time since start;"
                 " click a road)", fontsize=9)

    # ---- how fast it got there
    ax2 = fig.add_subplot(gs[1, 1])
    xs = [0.0] + [s_["cum_km"] for s_ in segs]
    ax2.plot(xs, cum, "-o", color=RED, ms=3, lw=2.2, label=f"with conditions: {total:.2f} min")
    ax2.plot(xs, [0.0] + [s_["cum_base"] for s_ in segs], "--", color="#9aa2c0", lw=1.8,
             label=f"no conditions (edges.csv): {base_total:.2f} min")
    if selected:
        s_ = segs[selected - 1]
        ax2.axvspan(s_["cum_km"] - s_["km"], s_["cum_km"], color=FRONTIER, alpha=0.3)
    ax2.set_xlabel("distance along the route (km)", fontsize=8)
    ax2.set_ylabel("time since start (min)", fontsize=8)
    ax2.tick_params(labelsize=7)
    ax2.legend(fontsize=7, frameon=False, loc="upper left")
    ax2.set_title("How fast it got there (steeper = slower)", fontsize=9)
    ax2.spines[["top", "right"]].set_visible(False)

    # ---- per segment
    ax3 = fig.add_subplot(gs[2, :])
    xs3 = [s_["i"] for s_ in segs]
    bars = ax3.bar(xs3, [s_["minutes"] for s_ in segs], color=[CMAP(NORM(s_["c"])) for s_ in segs],
                   edgecolor=[DARK if s_["i"] == selected else "none" for s_ in segs], lw=2)
    for b, s_ in zip(bars, segs):
        b.set_picker(True); b.set_gid(f"seg:{s_['i']}")
    ax3.bar(xs3, [s_["base_minutes"] for s_ in segs], fill=False, edgecolor="#5d647d", ls="--", lw=1)
    ax3.set_ylim(0, max(max(s_["minutes"], s_["base_minutes"]) for s_ in segs) * 1.3)
    if len(segs) <= 18:
        for s_ in segs:
            ax3.text(s_["i"], s_["minutes"], f"{s_['eff']:.0f}\nkm/h", ha="center", va="bottom", fontsize=6.5)
    ax3.set_xlabel("road segment (click a bar)", fontsize=8)
    ax3.set_ylabel("min", fontsize=8)
    ax3.tick_params(labelsize=7)
    ax3.set_xticks(xs3[::max(1, len(xs3) // 20)])
    ax3.spines[["top", "right"]].set_visible(False)
    ax3.set_title("Minutes per road segment (colour = E[congestion], label = effective speed, "
                  "dashed = no conditions)", fontsize=9)


def default_selected(segs):
    """The slowest segment (most minutes per km) - a good one to explain first."""
    return max(segs, key=lambda s: s["minutes"] / max(s["km"], 1e-6))["i"] if segs else None


def method_listing(name):
    """(header, [(line text, is_key_line)]) for the code view."""
    src, first, path = VT.method_source(name)
    pats = KEY_LINES.get(name, [])
    rows = [(f"{first + i:4d}  {line}", any(p in line for p in pats)) for i, line in enumerate(src)]
    return f"{name}  ({path.rsplit('/', 1)[-1]}:{first})  -  {VT.METHODS[name][1]}", rows


# ===================================================================== tkinter parts
class StepTab:
    """Animated UCS vs A* with the real search.py code highlighted line by line."""

    def __init__(self, nb, app):
        tk, ttk = app.tk, app.ttk
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.figure import Figure
        self.app, self.tk = app, tk
        self.frame = ttk.Frame(nb)
        nb.add(self.frame, text="Step-by-step (code)")
        pane = ttk.PanedWindow(self.frame, orient="vertical")
        pane.pack(fill="both", expand=True)
        top, bottom = ttk.Frame(pane), ttk.Frame(pane)
        pane.add(top, weight=3)
        pane.add(bottom, weight=2)
        self.fig = Figure(figsize=(10, 3.6), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=top)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        bottom.columnconfigure(0, weight=1)
        bottom.rowconfigure(2, weight=1)
        bar = ttk.Frame(bottom, padding=(6, 2))
        bar.grid(row=0, column=0, sticky="ew")
        self.play_btn = ttk.Button(bar, text="▶ Play", command=self.toggle)
        self.play_btn.pack(side="left")
        ttk.Button(bar, text="⏭ Step", command=lambda: self.advance(1)).pack(side="left", padx=2)
        ttk.Button(bar, text="⏩ Next expansion", command=self.next_expand).pack(side="left", padx=2)
        ttk.Button(bar, text="⏹ To the end", command=self.finish).pack(side="left", padx=2)
        ttk.Button(bar, text="⟲ Restart", command=self.restart).pack(side="left", padx=2)
        ttk.Label(bar, text="  speed (steps per frame)").pack(side="left")
        self.speed = tk.IntVar(value=1)
        ttk.Scale(bar, from_=1, to=200, variable=self.speed, orient="horizontal", length=180).pack(side="left")
        self.result = ttk.Label(bar, text="", foreground="#1a1f3d")
        self.result.pack(side="left", padx=10)

        ttk.Label(bottom, text="drag the divider above to give the code more room",
                  foreground="#9aa2c0").grid(row=1, column=0, sticky="e")
        codes = ttk.Frame(bottom)
        codes.grid(row=2, column=0, sticky="nsew")
        codes.rowconfigure(0, weight=1)
        self.text, self.status = {}, {}
        for i, algo in enumerate(ALGOS):
            col = ttk.Frame(codes, padding=4)
            col.grid(row=0, column=i, sticky="nsew")
            codes.columnconfigure(i, weight=1)
            col.columnconfigure(0, weight=1)
            col.rowconfigure(1, weight=1)  # the code box takes (and gives back) the spare height
            tk.Label(col, text=f"{ALGO_NAME[algo]}  -  search.py, the code that runs (line, times run, code)",
                     fg="white", bg=ALGO_COLOR[algo], anchor="w", font=("sans", 9, "bold")).grid(row=0, column=0, sticky="ew")
            t = tk.Text(col, height=4, font=("monospace", 9), wrap="none", bg="#fbfbfe")
            t.grid(row=1, column=0, sticky="nsew")
            s = tk.Label(col, text="", justify="left", anchor="w", font=("monospace", 9), bg="#f4f5fa", wraplength=620)
            s.grid(row=2, column=0, sticky="ew")
            self.status[algo] = s
            t.tag_configure("cur", background=ALGO_LIGHT[algo], foreground="#000000", font=("monospace", 9, "bold"))
            t.tag_configure("arrow", foreground=RELAX, font=("monospace", 9, "bold"))
            t.tag_configure("cold", foreground="#a0a4b8")
            t.tag_configure("hot", foreground="#1a1f3d")
            self.text[algo] = t
        self.src = {a: VT.code_lines(a) for a in ALGOS}
        self.playing, self.key, self.view = False, None, None

    # ---- life cycle
    def refresh(self, st, res):
        key = (st["graph"], st["weather"], st["time"], st["road_class"], st["expected_time"], st["cost"],
               st["src"], st["dst"])
        if key != self.key:
            self.key, self.st, self.res = key, st, res
            self.restart()

    def restart(self):
        self.playing = False
        self.play_btn.config(text="▶ Play")
        st, g = self.st, self.res["g"]
        self.gens = {a: VT.trace(g, st["src"], st["dst"], st["cost"], a) for a in ALGOS}
        self.states, self.over = {}, {a: False for a in ALGOS}
        for a in ALGOS:
            _, self.states[a] = next(self.gens[a])
        self.view = StepView(self.fig, g, st)
        self.render()

    def advance(self, n):
        for a in ALGOS:
            for _ in range(n):
                if self.over[a]:
                    break
                try:
                    _, self.states[a] = next(self.gens[a])
                except StopIteration:
                    self.over[a] = True
        self.render()

    def next_expand(self):
        for a in ALGOS:
            while not self.over[a]:
                try:
                    ev, self.states[a] = next(self.gens[a])
                except StopIteration:
                    self.over[a] = True
                    break
                if ev in ("expand", "fail"):
                    break
        self.render()

    def finish(self):
        self.advance(10 ** 7)

    def toggle(self):
        self.playing = not self.playing
        self.play_btn.config(text="⏸ Pause" if self.playing else "▶ Play")
        if self.playing:
            self.tick()

    def tick(self):
        if not self.playing:
            return
        self.advance(max(1, int(self.speed.get())))
        if all(self.over[a] or self.states[a].finished for a in ALGOS):
            self.playing = False
            self.play_btn.config(text="▶ Play")
            return
        self.app.root.after(90, self.tick)

    # ---- drawing
    def render(self):
        for a in ALGOS:
            self.view.update(a, self.states[a])
            self.render_code(a)
        self.canvas.draw_idle()
        su, sa = self.states["ucs"], self.states["astar"]
        if su.finished and sa.finished:
            same = (su.path is None and sa.path is None) or abs(su.cost - sa.cost) < 1e-9
            self.result.config(text=f"A* reached the goal in {sa.steps} steps ({sa.expanded} expanded), "
                                    f"UCS in {su.steps} steps ({su.expanded} expanded). Same cost: "
                                    f"{'yes' if same else 'NO'} ({sa.cost:.2f})")
        elif sa.finished:
            self.result.config(text=f"A* is done after {sa.steps} steps - UCS is still searching ...")
        else:
            self.result.config(text="")

    def render_code(self, algo):
        src, first, idx = self.src[algo]
        s = self.states[algo]
        line_hits = {}
        for ev, n in s.hits.items():
            if ev in idx:
                line_hits[idx[ev]] = line_hits.get(idx[ev], 0) + n
        t = self.text[algo]
        t.config(state="normal")
        t.delete("1.0", "end")
        cur = idx.get(s.event)
        for i, line in enumerate(src):
            h = line_hits.get(i, 0)
            mark = "➜" if i == cur else " "
            t.insert("end", f"{mark}{first + i:4d} {h:>6} │ ", ("arrow",) if i == cur else ())
            tag = "cur" if i == cur else ("hot" if h else "cold")
            t.insert("end", line + "\n", (tag,))
        if cur is not None:
            def scroll(t=t, cur=cur, n=len(src)):
                t.see(f"{max(cur - 2, 1)}.0"); t.see(f"{min(cur + 4, n)}.0"); t.see(f"{cur + 1}.0")
            scroll()
            t.after_idle(scroll)  # again once the window has its final size
        t.config(state="disabled")
        nm = lambda n: f"{n} ({self.res['g'].nodes[n][0]})" if n in self.res["g"].nodes and len(self.res["g"].nodes) <= 70 else str(n)
        lines = [f"{ALGO_NAME[algo]}: {VT.EVENT_TEXT.get(s.event, '')}"]
        if s.u is not None and s.g is not None:
            lines.append(f"  node {nm(s.u)}:  g = {s.g:.2f}" + (f"   h = {s.h:.2f}   f = g + h = {s.f:.2f}"
                                                                   if algo == "astar" else "   (UCS: f = g, no h)"))
        if s.event in ("relax", "test", "push") and s.v is not None:
            old = s.best.get(s.v)
            lines.append(f"  road {s.u} -> {s.v}: cost {s.w:.2f}, new g = {s.nc:.2f}"
                         + (f"  (best before {old:.2f})" if old is not None and s.event != "push" else ""))
        fr = s.frontier(5)
        if fr:
            lines.append("  queue (cheapest first): " + "  ".join(f"{n} f={f:.2f}" for f, _, _, n in fr))
        lines.append(f"  expanded {s.expanded}  |  pushed {s.pushes}  |  steps {s.steps}"
                     + (f"  |  FINISHED cost {s.cost:.2f}" if s.finished and s.path else ""))
        self.status[algo].config(text="\n".join(lines))


class RouteTab:
    """Route details + clickable pipeline / segments + code of the method used."""

    def __init__(self, nb, app):
        tk, ttk = app.tk, app.ttk
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.figure import Figure
        self.app, self.tk = app, tk
        self.frame = ttk.Frame(nb)
        nb.add(self.frame, text="Route details")
        pane = ttk.PanedWindow(self.frame, orient="horizontal")
        pane.pack(fill="both", expand=True)
        left, right = ttk.Frame(pane), ttk.Frame(pane, padding=4)
        pane.add(left, weight=3)
        pane.add(right, weight=2)
        self.fig = Figure(figsize=(9, 7), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=left)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.canvas.mpl_connect("pick_event", self.on_pick)
        tk.Label(right, text="What happened here (click the route, a bar, or a method box)", anchor="w",
                 font=("sans", 9, "bold")).pack(fill="x")
        self.text = tk.Text(right, width=56, font=("monospace", 9), wrap="none", bg="#fbfbfe")
        hs = ttk.Scrollbar(right, orient="horizontal", command=self.text.xview)
        self.text.configure(xscrollcommand=hs.set)
        hs.pack(side="bottom", fill="x")
        sb = ttk.Scrollbar(right, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(fill="both", expand=True)
        t = self.text
        t.tag_configure("h1", font=("sans", 11, "bold"), foreground=DARK)
        t.tag_configure("calc", font=("monospace", 9), foreground=DARK)
        t.tag_configure("code", foreground="#6b708a")
        t.tag_configure("key", background="#fff1a8", foreground="#000000", font=("monospace", 9, "bold"))
        t.tag_configure("hdr", foreground="white", background="#5b52a8", font=("monospace", 9, "bold"))
        self.key, self.selected, self.method = None, None, None

    def refresh(self, st, res):
        key = (st["graph"], st["weather"], st["time"], st["road_class"], st["expected_time"], st["cost"],
               st["src"], st["dst"])
        if key == self.key:
            return
        self.key, self.st, self.res = key, st, res
        self.segs = VT.route_segments(res["g"], res["base"], res["astar"]["path"]) if res["astar"]["path"] else []
        self.selected, self.method = default_selected(self.segs), None
        self.redraw()
        self.explain_segment()

    def redraw(self):
        draw_route(self.fig, self.st, self.res, self.segs, self.selected, self.method)
        self.canvas.draw_idle()

    def on_pick(self, ev):
        gid = ev.artist.get_gid() or ""
        if gid.startswith("seg:"):
            self.selected, self.method = int(gid[4:]), None
            self.redraw(); self.explain_segment()
        elif gid.startswith("method:"):
            self.method = gid[7:]
            self.redraw(); self.show_methods([self.method], intro=None)

    def explain_segment(self):
        if not self.segs:
            self._write([("No route between these places.\n", "h1")])
            return
        s = self.segs[self.selected - 1]
        calc, used = VT.explain_edge(s, self.st)
        self.show_methods(used, intro=(f"Road segment {s['i']} of {len(self.segs)}: {s['minutes']:.2f} min "
                                       f"(cumulative {s['cum_min']:.2f} min)\n", calc))

    def show_methods(self, names, intro):
        parts = []
        if intro:
            parts += [(intro[0], "h1"), (intro[1] + "\n\n", "calc")]
        parts.append(("Code that produced it (highlighted = the line that matters):\n\n", "h1"))
        for name in names:
            hdr, rows = method_listing(name)
            parts.append((f" {hdr} \n", "hdr"))
            for line, key in rows:
                parts.append((line + "\n", "key" if key else "code"))
            parts.append(("\n", "code"))
        self._write(parts)

    def _write(self, parts):
        t = self.text
        t.config(state="normal")
        t.delete("1.0", "end")
        for s, tag in parts:
            t.insert("end", s, (tag,))
        t.config(state="disabled")
