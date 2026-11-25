"""viz_trace.py - logic behind the visualizer's "Step-by-step" and "Route details" tabs.

* trace()        UCS / A* as generators: the SAME steps as search.ucs / search.astar
                 (same heap, same tie-breaking), yielding an event per code line,
                 so the visualizer can animate them and highlight the real source.
* code_lines()   the real source of search.ucs / search.astar and, for every
                 event, the line number it corresponds to.
* route_segments(), explain_edge(), METHODS: what the Route tab shows - every
                 segment's numbers, the full calculation of one edge, and the
                 source of each method in the pipeline.

Standard library only. test_visualizer.py checks trace() == search.py on all pairs.
"""
import heapq
import inspect
import itertools
import math

import graph as graph_mod
import search
import traffic as T
from graph import haversine_km

# event -> text that identifies its line in search.py (first match inside the function)
LINE_PATTERNS = {
    "ucs": {"init": "pq = [(0.0", "pop": "heapq.heappop(pq)", "skip": "if u in done", "expand": "done.add(u)",
            "goal": "if u == goal", "relax": "nc = c + w", "test": "if nc < best.get", "push": "heapq.heappush",
            "fail": "return None"},
    "astar": {"init": "pq = [(h(start)", "pop": "heapq.heappop(pq)", "skip": "if u in done", "expand": "done.add(u)",
              "goal": "if u == goal", "relax": "nc = c + w", "test": "if nc < best.get", "push": "heapq.heappush",
              "fail": "return None", "h": "return g.heuristic_time_min(n, goal)"},
}
EVENT_TEXT = {"init": "put the start on the priority queue", "pop": "take the cheapest entry off the queue",
              "skip": "already expanded -> skip (stale queue entry)", "expand": "expand this node",
              "goal": "goal reached -> rebuild the path", "relax": "look at a road to a neighbour",
              "test": "is this a cheaper way to the neighbour?", "push": "yes -> remember it and push on the queue",
              "fail": "queue empty -> no route"}


def code_lines(algo):
    """(source lines of search.ucs / search.astar, first line number in search.py,
    {event: index into the source lines})."""
    fn = search.ucs if algo == "ucs" else search.astar
    src, first = inspect.getsourcelines(fn)
    src = [s.rstrip("\n") for s in src]
    idx = {}
    for ev, pat in LINE_PATTERNS[algo].items():
        hits = [i for i, s in enumerate(src) if pat in s]
        if not hits:
            raise RuntimeError(f"search.{fn.__name__} changed: '{pat}' not found")
        idx[ev] = hits[0]
    return src, first, idx


class TraceState:
    """Everything the animation shows; updated in place by trace()."""

    def __init__(self, algo, start, goal):
        self.algo, self.start, self.goal = algo, start, goal
        self.pq, self.best, self.parent, self.done = [], {start: 0.0}, {start: None}, set()
        self.expanded = self.pushes = self.steps = 0
        self.u = self.v = None
        self.g = self.h = self.f = None
        self.w = self.nc = None
        self.path, self.cost, self.finished = None, None, False
        self.hits = {}
        self.event = None

    def frontier(self, k=8):
        """Best k live entries: (f, g, h, node)."""
        out, seen = [], set()
        for e in sorted(self.pq, key=lambda e: (e[0], e[1])):
            node = e[-1]
            if node in self.done or node in seen:
                continue
            seen.add(node)
            g_ = e[2] if self.algo == "astar" else e[0]
            out.append((e[0], g_, e[0] - g_, node))
            if len(out) == k:
                break
        return out


def trace(g, start, goal, cost="time", algo="astar"):
    """Generator: runs UCS or A* exactly like search.py and yields
    (event, state) after every step. The final state holds path / cost / expanded."""
    ci = 2 if cost == "time" else 1
    st = TraceState(algo, start, goal)

    def h(n):
        if algo == "ucs":
            return 0.0
        if cost == "time":
            return g.heuristic_time_min(n, goal)
        _, la, lo = g.nodes[n]
        _, lb, lob = g.nodes[goal]
        return haversine_km(la, lo, lb, lob)

    def emit(ev):
        st.event = ev
        st.steps += 1
        st.hits[ev] = st.hits.get(ev, 0) + 1
        return ev, st

    tie = itertools.count()
    st.pq = [(0.0, next(tie), start)] if algo == "ucs" else [(h(start), next(tie), 0.0, start)]
    st.u = start
    yield emit("init")
    while st.pq:
        item = heapq.heappop(st.pq)
        c, u = (item[0], item[2]) if algo == "ucs" else (item[2], item[3])
        st.u, st.v, st.g, st.h = u, None, c, h(u)
        st.f = c + st.h
        yield emit("pop")
        if u in st.done:
            yield emit("skip")
            continue
        st.done.add(u)
        st.expanded += 1
        yield emit("expand")
        if u == goal:
            path = [goal]
            while st.parent[path[-1]] is not None:
                path.append(st.parent[path[-1]])
            st.path, st.cost, st.finished = path[::-1], c, True
            yield emit("goal")
            return
        for nb in g.neighbors(u):
            v, w = nb[0], nb[ci]
            nc = c + w
            st.v, st.w, st.nc = v, w, nc
            yield emit("relax")
            better = nc < st.best.get(v, float("inf"))
            yield emit("test")
            if better:
                st.best[v] = nc
                st.parent[v] = u
                if algo == "ucs":
                    heapq.heappush(st.pq, (nc, next(tie), v))
                else:
                    heapq.heappush(st.pq, (nc + h(v), next(tie), nc, v))
                st.pushes += 1
                yield emit("push")
    st.finished, st.cost = True, float("inf")
    yield emit("fail")


def run_trace(g, start, goal, cost="time", algo="astar"):
    st = None
    for _, st in trace(g, start, goal, cost, algo):
        pass
    return st


# ----------------------------------------------------------------- route details
def _edge(g, a, b):
    return min((e for e in g.adj[a] if e["dst"] == b), key=lambda e: e["time_min"])


def route_segments(g_cond, g_base, path):
    """One dict per road segment of `path`: numbers on the conditioned graph and
    on the base graph (edges.csv, no conditions) for comparison."""
    out, cum_t, cum_b, cum_km = [], 0.0, 0.0, 0.0
    for i, (a, b) in enumerate(zip(path, path[1:])):
        e, eb = _edge(g_cond, a, b), _edge(g_base, a, b)
        c = e["congestion"]
        eff = e["speed_kmh"] * (1 - 0.7 * c)
        cum_t += e["time_min"]; cum_b += eb["time_min"]; cum_km += e["distance_km"]
        out.append(dict(i=i + 1, a=a, b=b, road=e["road"], highway=e.get("highway") or "",
                        cls=T.road_class(e["speed_kmh"], e.get("highway")), km=e["distance_km"],
                        speed=e["speed_kmh"], base=e.get("base_congestion", eb["congestion"]), c=c,
                        eff=eff, minutes=e["time_min"], base_minutes=eb["time_min"],
                        cum_min=cum_t, cum_base=cum_b, cum_km=cum_km))
    return out


def explain_edge(seg, st):
    """Step-by-step calculation of one segment with the numbers filled in
    (the same formulas as traffic.py / graph.py)."""
    lines = [f"Segment {seg['i']}: {seg['a']} -> {seg['b']}  ({seg['road']})",
             f"  length {seg['km']:.3f} km, speed limit {seg['speed']:.0f} km/h, "
             f"base congestion (edges.csv) {seg['base']:.2f}"]
    if not (st["weather"] or st["time"]):
        lines += ["  no --weather/--time: graph.py uses the base congestion directly",
                  f"  time = {seg['km']:.3f} / ({seg['speed']:.0f} * (1 - 0.7*{seg['base']:.2f})) * 60"
                  f" = {seg['minutes']:.2f} min"]
        return "\n".join(lines), ["Graph.travel_time_min"]
    p = T.congestion_dist(st["weather"], st["time"])
    k = T.ROAD_CLASS_K[seg["cls"]] if st["road_class"] else 1.0
    lines.append(f"1. Bayesian network: P(C | W={st['weather'] or '?'}, T={st['time'] or '?'}) = "
                 + ", ".join(f"{l} {p[l]:.2f}" for l in T.LEVEL))
    lines.append(f"2. road class: {seg['cls']}" + (f" (OSM highway={seg['highway']})" if seg["highway"] else
                                                     f" (speed {seg['speed']:.0f} km/h)")
                 + (f" -> k = {k}" if st["road_class"] else " -> k = 1 (uniform model)"))
    cl = {l: T.edge_congestion(seg["base"], l, k) for l in T.LEVEL}
    lines.append("3. c(level) = clip(base + k*shift, 0, 0.95): "
                 + ", ".join(f"{l} {seg['base']:.2f}{k * T.SHIFT[l]:+.3f} -> {cl[l]:.3f}" for l in T.LEVEL))
    ec = sum(p[l] * cl[l] for l in T.LEVEL)
    lines.append("4. E[c] = " + " + ".join(f"{p[l]:.2f}*{cl[l]:.3f}" for l in T.LEVEL) + f" = {ec:.4f}")
    used = ["traffic.congestion_dist", "traffic.edge_congestion", "traffic.expected_edge_congestion"]
    if st["expected_time"]:
        tl = {l: graph_mod.Graph.travel_time_min(seg["km"], seg["speed"], cl[l]) for l in T.LEVEL}
        lines.append("5. E[t] = sum P(l) * time(c(l)): " + " + ".join(f"{p[l]:.2f}*{tl[l]:.2f}" for l in T.LEVEL)
                     + f" = {sum(p[l] * tl[l] for l in T.LEVEL):.3f} -> {seg['minutes']:.2f} min")
        used.append("traffic.expected_edge_time")
    else:
        lines.append(f"5. time = {seg['km']:.3f} / ({seg['speed']:.0f} * (1 - 0.7*{ec:.4f})) * 60 = "
                     f"{seg['minutes']:.2f} min   (effective speed {seg['eff']:.1f} km/h)")
    used.append("Graph.travel_time_min")
    lines.append(f"   without conditions: {seg['base_minutes']:.2f} min "
                 f"({seg['minutes'] - seg['base_minutes']:+.2f} min)")
    return "\n".join(lines), used


# methods in the pipeline: name -> (function, short description)
METHODS = {
    "Graph.load": (graph_mod.Graph._add_road, "edges.csv -> edge with distance, speed, base congestion"),
    "traffic.congestion_dist": (T.congestion_dist, "Bayesian network: P(C | weather, time)"),
    "traffic.edge_congestion": (T.edge_congestion, "one road on a low / medium / high day (road-class k)"),
    "traffic.expected_edge_congestion": (T.expected_edge_congestion, "E[c] of one road"),
    "traffic.expected_edge_time": (T.expected_edge_time, "E[t] of one road (--expected-time)"),
    "traffic.apply_conditions": (T.apply_conditions, "puts the expected values on every edge"),
    "Graph.travel_time_min": (graph_mod.Graph.travel_time_min, "time = dist / (speed * (1 - 0.7c)) * 60"),
    "search.ucs": (search.ucs, "Uniform-Cost Search"),
    "search.astar": (search.astar, "A* with the straight-line heuristic"),
}


def method_source(name):
    fn = METHODS[name][0]
    src, first = inspect.getsourcelines(fn)
    return [s.rstrip("\n") for s in src], first, inspect.getsourcefile(fn)


def pipeline(st):
    """Boxes of the Route tab: (label, method name, active?, colour)."""
    cond = bool(st["weather"] or st["time"])
    return [("edges.csv", "Graph.load", True, "#9aa2c0"),
            ("Bayes net\nP(C|W,T)", "traffic.congestion_dist", cond, "#e5473e"),
            ("road class k", "traffic.edge_congestion", cond and st["road_class"], "#f2a541"),
            ("E[c] -> time", "traffic.expected_edge_congestion", cond and not st["expected_time"], "#1f9d62"),
            ("E[t]", "traffic.expected_edge_time", cond and st["expected_time"], "#1f9d62"),
            ("UCS", "search.ucs", True, "#9aa2c0"),
            ("A*", "search.astar", True, "#5b52a8")]
