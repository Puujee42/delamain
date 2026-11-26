"""graph.py - Week X: road graph data loader (Ulaanbaatar).

Reads nodes.csv + edges.csv, builds a directed weighted graph, checks
direction (one-way) and congestion, and prints a validation report.
Used later by search.py (UCS / A*) and traffic.py (Bayesian network).

NOTE: coordinates are approximate and congestion values are SYNTHETIC
(no real traffic data yet - see the "Risk" slide). Replace with OSM /
measured data later.
"""
import csv
import math
import os
from array import array
from collections import defaultdict

DETOUR_FACTOR = 1.3  # straight-line -> road length
# Traffic lights (only for data with a `signals` column, e.g. the OSM station graphs).
# Expected wait per light in free traffic: uniform delay r^2 / (2C) for a 90 s cycle with
# 45 s red = 11 s, plus ~4 s to stop and start -> 15 s = 0.25 min. Queues grow with
# congestion c, so the wait is 0.25 * (1 + 2c) min (c = 0.95 -> ~0.7 min). ASSUMED values.
SIGNAL_DELAY_MIN = 0.25
SIGNAL_CONGESTION_FACTOR = 2.0


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class Graph:
    def __init__(self):
        self.nodes = {}                  # id -> (name, lat, lon)
        self.adj = defaultdict(list)     # id -> list of edge dicts
        self.edges = []                  # raw directed edges
        # A* heuristic speed: the fastest road in the graph, never below 70 km/h
        # (70 on the city graph, so Week XII-XIV numbers are unchanged).
        self.max_speed_kmh = 70.0
        # Measured lengths (OSM length_km) can be as short as the straight line,
        # so times are then rounded UP to keep the heuristic consistent.
        self.ceil_time = False
        self.time_decimals = 2

    # ---------- loading ----------
    def load(self, nodes_csv="nodes.csv", edges_csv="edges.csv"):
        with open(nodes_csv, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                self.nodes[r["id"]] = (r["name"], float(r["lat"]), float(r["lon"]))
        with open(edges_csv, encoding="utf-8") as f:
            rd = csv.DictReader(f)
            # data with traffic-light counts (the OSM station graphs) is built from many short street
            # pieces: keep times to 0.0001 min there, so per-piece rounding does not add up
            if "signals" in (rd.fieldnames or []):
                self.time_decimals = 4
            for r in rd:
                self._add_road(r)
        lm = os.path.join(os.path.dirname(os.path.abspath(edges_csv)), "landmarks.csv")
        if os.path.exists(lm):
            self._load_landmarks(lm)
        return self

    def _load_landmarks(self, path):
        """ALT landmark tables (written by make_ub_graph.py for the full street graph):
        free-flow travel times from and to a few landmark junctions."""
        with open(path, encoding="utf-8") as f:
            rd = csv.reader(f)
            head = next(rd)
            k = (len(head) - 1) // 2
            self.alt_idx, frm, to = {}, [array("d") for _ in range(k)], [array("d") for _ in range(k)]
            for i, r in enumerate(rd):
                self.alt_idx[r[0]] = i
                for j in range(k):
                    frm[j].append(float(r[1 + j]))
                    to[j].append(float(r[1 + k + j]))
        self.alt_from, self.alt_to = frm, to

    def _add_road(self, r):
        a, b = r["from"], r["to"]
        if a not in self.nodes or b not in self.nodes:
            raise ValueError(f"Unknown node in edge {a}->{b}")
        if int(r["blocked"]) == 1:
            return  # closed road: skipped (still reported by validate())
        _, la, lo = self.nodes[a]
        _, lb, lob = self.nodes[b]
        # real length (km) from OSM when available, else straight line x detour factor
        if r.get("length_km"):
            # a road is never shorter than the straight line; round up (km, 3 dp)
            dist = math.ceil(max(float(r["length_km"]), haversine_km(la, lo, lb, lob)) * 1000) / 1000
            self.ceil_time = True
        else:
            dist = haversine_km(la, lo, lb, lob) * DETOUR_FACTOR
        speed = float(r["speed_limit_kmh"])
        self.max_speed_kmh = max(self.max_speed_kmh, speed)
        cong = float(r["base_congestion"])
        # traffic lights on this road piece (0 if not recorded); a pedestrian-crossing light counts 0.5
        signals = float(r.get("signals") or 0)
        edge = {
            "road": r["road"],
            "highway": r.get("highway") or "",
            "distance_km": round(dist, 3),
            "speed_kmh": speed,
            "congestion": cong,
            "signals": signals,
            "time_min": self.round_time(self.travel_time_min(dist, speed, cong)
                                        + self.signal_delay_min(signals, cong)),
        }
        self._push(a, b, edge)
        if int(r["oneway"]) == 0:
            self._push(b, a, edge)

    def _push(self, a, b, edge):
        e = dict(edge, src=a, dst=b)
        self.adj[a].append(e)
        self.edges.append(e)

    # ---------- weights ----------
    @staticmethod
    def travel_time_min(dist_km, speed_kmh, congestion):
        """Congestion 0..1 slows traffic: effective speed = speed*(1-0.7*c)."""
        eff = speed_kmh * (1 - 0.7 * congestion)
        return dist_km / eff * 60

    @staticmethod
    def signal_delay_min(signals, congestion):
        """Expected waiting time (min) at `signals` traffic lights at congestion 0..1."""
        return signals * SIGNAL_DELAY_MIN * (1 + SIGNAL_CONGESTION_FACTOR * congestion)

    def round_time(self, t):
        """Minutes to 2 decimals: nearest (default), or up for measured lengths."""
        if self.ceil_time:
            q = 10 ** self.time_decimals
            return math.ceil(t * q) / q
        return round(t, 2)

    def neighbors(self, node):
        return [(e["dst"], e["distance_km"], e["time_min"]) for e in self.adj[node]]

    def heuristic_time_min(self, node, goal, max_speed_kmh=None):
        """Admissible A* heuristic: straight-line distance at top speed
        (70 km/h, or the fastest road in the graph if that is faster).
        With ALT landmark tables (full street graph) also the landmark bound:
        for every landmark L, d(n, goal) >= d(L, goal) - d(L, n) and >= d(n, L) - d(goal, L),
        where d is the FREE-FLOW time (speed limit, no congestion, no lights). Every real
        edge time is >= its free-flow time, so the bound stays admissible and consistent
        under every weather / time condition."""
        _, la, lo = self.nodes[node]
        _, lb, lob = self.nodes[goal]
        h = haversine_km(la, lo, lb, lob) / (max_speed_kmh or self.max_speed_kmh) * 60
        idx = getattr(self, "alt_idx", None)
        if idx is not None and node in idx and goal in idx:
            if getattr(self, "_alt_goal", None) != goal:  # one search = one goal: look its values up once
                j = idx[goal]
                self._alt_goal = goal
                self._alt_g = [(frm, frm[j] - 1e-6, to, to[j] + 1e-6) for frm, to in zip(self.alt_from, self.alt_to)]
            i = idx[node]
            for frm, fg, to, tg in self._alt_g:  # 1e-6: margin for the rounding in landmarks.csv
                a, b = fg - frm[i], to[i] - tg
                if a > h:
                    h = a
                if b > h:
                    h = b
        return h

    # ---------- validation ----------
    def validate(self):
        issues = []
        # congestion range
        for e in self.edges:
            if not 0 <= e["congestion"] <= 1:
                issues.append(f"Bad congestion {e['congestion']} on {e['src']}->{e['dst']}")
        # one-way streets: no reverse edge
        pairs = {(e["src"], e["dst"]) for e in self.edges}
        oneway = sorted(p for p in pairs if (p[1], p[0]) not in pairs)
        # connectivity (BFS following direction from first node)
        start = next(iter(self.nodes))
        seen, stack = {start}, [start]
        while stack:
            u = stack.pop()
            for e in self.adj[u]:
                if e["dst"] not in seen:
                    seen.add(e["dst"])
                    stack.append(e["dst"])
        unreachable = sorted(set(self.nodes) - seen)
        heavy = sorted((e for e in self.edges if e["congestion"] >= 0.7),
                       key=lambda e: -e["congestion"])
        return {"issues": issues, "oneway": oneway,
                "unreachable_from_start": unreachable, "heavy": heavy}

    def report(self):
        v = self.validate()
        name = lambda i: self.nodes[i][0]
        print("=== Road graph report (Week X) ===")
        print(f"Nodes: {len(self.nodes)} | Directed edges: {len(self.edges)}")
        print(f"Total road length (one direction each): "
              f"{sum(e['distance_km'] for e in self.edges) / 2:.1f} km (approx)")
        print("\nOne-way edges:")
        for a, b in v["oneway"]:
            print(f"  {name(a)} -> {name(b)}")
        print("\nHeavily congested edges (>= 0.7):")
        seen = set()
        for e in v["heavy"]:
            key = frozenset((e["src"], e["dst"]))
            if key in seen:
                continue
            seen.add(key)
            print(f"  {name(e['src'])} - {name(e['dst'])}: "
                  f"{e['congestion']:.1f} ({e['road']}, {e['time_min']} min)")
        print("\nUnreachable from first node:",
              [name(i) for i in v["unreachable_from_start"]] or "none")
        print("Data issues:", v["issues"] or "none")


if __name__ == "__main__":
    Graph().load().report()
