"""scale_test.py - Week XIII: does A* still save work on a bigger graph?

1. Generates a synthetic 64-node road graph (8 x 8 jittered grid over the
   Ulaanbaatar area, seed fixed -> same graph every run) into data_scale/
   in the same CSV format as nodes.csv / edges.csv.
2. Runs UCS and A* on ALL ordered pairs (i != j) for cost = time and dist,
   with the default congestion and under 3 Bayesian weather/time conditions.
3. Reports average nodes expanded and the % reduction of A* vs UCS the same
   way as Week XII:  reduction = 1 - mean(A* expanded) / mean(UCS expanded),
   shown as "time / dist".  The 15-node city graph is reported the same way.

    python3 scale_test.py            # writes data_scale/ and results/scale_week13.csv
"""
import csv
import math
import os
import random
import statistics as st

from graph import Graph
from search import ucs, astar
from traffic import apply_conditions

SEED = 13
ROWS = COLS = 8                     # 64 nodes
LAT0, LAT1 = 47.86, 47.96           # Ulaanbaatar area (same bbox as audit.py check)
LON0, LON1 = 106.78, 107.02
SPEEDS = [40, 50, 60, 70]           # <= 70 km/h so h = straight line / 70 stays admissible
CONDITIONS = [(None, None), ("clear", "off_peak"), ("rain", "morning_peak"), ("snow", "morning_peak")]
OUT_DIR, RESULTS = "data_scale", "results/scale_week13.csv"


def _strongly_connected(ids, edges):
    adj, radj = {i: [] for i in ids}, {i: [] for i in ids}
    for a, b, one in edges:
        adj[a].append(b); radj[b].append(a)
        if not one:
            adj[b].append(a); radj[a].append(b)

    def reach(g):
        seen, stack = {ids[0]}, [ids[0]]
        while stack:
            for v in g[stack.pop()]:
                if v not in seen:
                    seen.add(v); stack.append(v)
        return len(seen) == len(ids)
    return reach(adj) and reach(radj)


def generate(out_dir=OUT_DIR, seed=SEED):
    rng = random.Random(seed)
    ids, pos = [], {}
    for r in range(ROWS):
        for c in range(COLS):
            i = f"S{r * COLS + c + 1:02d}"
            lat = LAT0 + (LAT1 - LAT0) * (r + 0.5 + rng.uniform(-0.3, 0.3)) / ROWS
            lon = LON0 + (LON1 - LON0) * (c + 0.5 + rng.uniform(-0.3, 0.3)) / COLS
            ids.append(i); pos[i] = (r, c, round(lat, 5), round(lon, 5))
    grid = {(p[0], p[1]): i for i, p in pos.items()}

    cand = []
    for (r, c), i in grid.items():
        for dr, dc, keep in [(0, 1, 0.92), (1, 0, 0.92), (1, 1, 0.25), (1, -1, 0.15)]:
            j = grid.get((r + dr, c + dc))
            if j and rng.random() < keep:
                cand.append((i, j))

    clat, clon = (LAT0 + LAT1) / 2, (LON0 + LON1) / 2
    edges = []
    for a, b in cand:
        one = rng.random() < 0.08
        edges.append((a, b, one))
    # fix one-way choices that break strong connectivity (turn them two-way)
    for k, (a, b, one) in enumerate(edges):
        if one and not _strongly_connected(ids, edges):
            edges[k] = (a, b, False)
    assert _strongly_connected(ids, edges), "generated graph is not strongly connected"

    os.makedirs(out_dir, exist_ok=True)
    with open(f"{out_dir}/nodes.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "lat", "lon"])
        for i in ids:
            r, c, lat, lon = pos[i]
            w.writerow([i, f"Grid r{r + 1}c{c + 1}", lat, lon])
    with open(f"{out_dir}/edges.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["from", "to", "road", "speed_limit_kmh", "oneway", "base_congestion", "blocked"])
        for a, b, one in edges:
            la, lo = (pos[a][2] + pos[b][2]) / 2, (pos[a][3] + pos[b][3]) / 2
            # synthetic: busier near the centre, quieter on the edge of the city
            dc = math.hypot((la - clat) / (LAT1 - LAT0), (lo - clon) / (LON1 - LON0))
            cong = min(0.9, max(0.1, 0.8 - 1.0 * dc + rng.uniform(-0.15, 0.15)))
            w.writerow([a, b, f"Road {a}-{b}", rng.choice(SPEEDS), int(one), round(cong, 2), 0])
    return out_dir


def measure(g):
    """Average nodes expanded over all ordered pairs (i != j), like Week XII."""
    ids = list(g.nodes)
    pairs = [(s, t) for s in ids for t in ids if s != t]
    res = {"pairs": len(pairs)}
    for cost in ("time", "dist"):
        nu, na, bad = [], [], 0
        for s, t in pairs:
            pu, cu, xu = ucs(g, s, t, cost)
            pa, ca, xa = astar(g, s, t, cost)
            nu.append(xu); na.append(xa)
            bad += (pu is None) != (pa is None) or abs(cu - ca) > 1e-9
        res[cost] = dict(ucs=st.mean(nu), astar=st.mean(na), mismatches=bad,
                         reduction=100 * (1 - st.mean(na) / st.mean(nu)))
    return res


def main():
    generate()
    graphs = {"city (15 nodes)": Graph().load(),
              "scale (64 nodes)": Graph().load(f"{OUT_DIR}/nodes.csv", f"{OUT_DIR}/edges.csv")}
    rows = []
    for gname, g in graphs.items():
        for w, t in CONDITIONS:
            gc = g if w is None else apply_conditions(g, w, t)
            m = measure(gc)
            rows.append({"graph": gname, "nodes": len(g.nodes), "directed_edges": len(g.edges),
                         "condition": "default" if w is None else f"{w}+{t}", "pairs": m["pairs"],
                         "ucs_nodes_time": round(m["time"]["ucs"], 2), "astar_nodes_time": round(m["time"]["astar"], 2),
                         "reduction_time_pct": round(m["time"]["reduction"], 1),
                         "ucs_nodes_dist": round(m["dist"]["ucs"], 2), "astar_nodes_dist": round(m["dist"]["astar"], 2),
                         "reduction_dist_pct": round(m["dist"]["reduction"], 1),
                         "optimal_same": f"{2 * m['pairs'] - m['time']['mismatches'] - m['dist']['mismatches']}/{2 * m['pairs']}"})
    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
    with open(RESULTS, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader(); wr.writerows(rows)

    print("A* vs UCS: average nodes expanded over all ordered pairs (i != j)")
    print(f"{'graph':17}{'condition':20}{'pairs':>6}  {'time UCS/A*':>13} {'dist UCS/A*':>13}  "
          f"{'reduction time / dist':>22}  optimal")
    for r in rows:
        print(f"{r['graph']:17}{r['condition']:20}{r['pairs']:>6}  "
              f"{r['ucs_nodes_time']:>6.2f}/{r['astar_nodes_time']:<6.2f} {r['ucs_nodes_dist']:>6.2f}/{r['astar_nodes_dist']:<6.2f}  "
              f"{'-' + str(round(r['reduction_time_pct'])) + '% / -' + str(round(r['reduction_dist_pct'])) + '%':>22}  {r['optimal_same']}")
    print(f"\nGraph written to {OUT_DIR}/, table to {RESULTS}")
    return rows


if __name__ == "__main__":
    main()
