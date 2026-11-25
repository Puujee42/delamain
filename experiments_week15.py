"""experiments_week15.py - Week XV experiments on the real OpenStreetMap graph.

  E1  UCS vs A* on the OSM graph of Ulaanbaatar (data_osm/, 1852 nodes):
      nodes expanded (time / dist, Week XII method), ms, optimality.
  E2  Route changes vs clear + off-peak on the OSM graph, uniform model vs
      road-class model (class from the OSM highway tag).
  E3  Expected travel time E[t] vs time at expected congestion t(E[c]) on the
      city, 64-node and OSM graphs: cost difference and route differences.

All pairs are used on the small graphs; on the OSM graph a fixed random sample
of N_OSM_PAIRS ordered pairs (seed 15). Outputs: results/week15_*.csv.
Offline: data_osm/ is built once from data_osm_raw/ub_tertiary.osm
(OpenStreetMap contributors, ODbL) with osm_to_graph.py.

    python3 experiments_week15.py
"""
import csv
import os
import random
import statistics as st
import time

from graph import Graph
from search import ucs, astar
from traffic import apply_conditions

SEED = 15
N_OSM_PAIRS = 500
OUT = "results"
CONDITIONS = [("clear", "off_peak"), ("rain", "morning_peak"), ("snow", "morning_peak"), ("snow", "evening_peak")]
REFERENCE = ("clear", "off_peak")
GRAPHS = [("city", ".", None), ("scale", "data_scale", None), ("osm", "data_osm", N_OSM_PAIRS)]


def load(folder):
    if folder == "data_scale" and not os.path.exists("data_scale/edges.csv"):
        import scale_test
        scale_test.generate()
    if folder == "data_osm" and not os.path.exists("data_osm/edges.csv"):
        raise SystemExit("data_osm/ missing: python3 osm_to_graph.py data_osm_raw/ub_tertiary.osm --out data_osm")
    return Graph().load(f"{folder}/nodes.csv", f"{folder}/edges.csv")


def sample_pairs(g, n=None, seed=SEED):
    ids = list(g.nodes)
    if n is None:
        return [(s, t) for s in ids for t in ids if s != t]
    rng = random.Random(seed)
    out = set()
    while len(out) < n:
        out.add(tuple(rng.sample(ids, 2)))
    return sorted(out)


def path_time(g, path):
    return sum(min(e["time_min"] for e in g.adj[a] if e["dst"] == b) for a, b in zip(path, path[1:]))


def e1_search(g, pairs):
    rows = []
    for w, t in [(None, None)] + CONDITIONS:
        gc = g if w is None else apply_conditions(g, w, t, by_class=True)
        row = dict(condition="default" if w is None else f"{w}+{t}", pairs=len(pairs))
        bad = 0
        for cost in ("time", "dist"):
            nu, na, mu, ma = [], [], 0.0, 0.0
            for s, d in pairs:
                t0 = time.perf_counter(); pu, cu, xu = ucs(gc, s, d, cost); t1 = time.perf_counter()
                pa, ca, xa = astar(gc, s, d, cost); t2 = time.perf_counter()
                nu.append(xu); na.append(xa); mu += t1 - t0; ma += t2 - t1
                bad += (pu is None) != (pa is None) or abs(cu - ca) > 1e-9
            row.update({f"ucs_nodes_{cost}": round(st.mean(nu), 1), f"astar_nodes_{cost}": round(st.mean(na), 1),
                        f"reduction_{cost}_pct": round(100 * (1 - st.mean(na) / st.mean(nu)), 1),
                        f"ucs_ms_{cost}": round(1000 * mu / len(pairs), 3), f"astar_ms_{cost}": round(1000 * ma / len(pairs), 3)})
        row["optimal_same"] = f"{2 * len(pairs) - bad}/{2 * len(pairs)}"
        rows.append(row)
    return rows


def route_changes(g, pairs, by_class, expected="congestion"):
    gref = apply_conditions(g, *REFERENCE, by_class=by_class, expected=expected)
    ref = {p: astar(gref, *p)[0] for p in pairs}
    rows = []
    for w, t in CONDITIONS:
        gc = apply_conditions(g, w, t, by_class=by_class, expected=expected)
        changed, saved = 0, []
        for p in pairs:
            pa, ca, _ = astar(gc, *p)
            if pa != ref[p]:
                changed += 1
                old = path_time(gc, ref[p])
                saved.append(100 * (old - ca) / old)
        rows.append(dict(condition=f"{w}+{t}", pairs=len(pairs), routes_changed=changed,
                         routes_changed_pct=round(100 * changed / len(pairs), 1),
                         avg_saved_pct_on_changed=round(st.mean(saved), 1) if saved else 0.0,
                         max_saved_pct=round(max(saved), 1) if saved else 0.0))
    return rows


def e2_routes(g, pairs):
    rows = []
    for model, by_class in (("uniform", False), ("road_class", True)):
        for r in route_changes(g, pairs, by_class):
            rows.append(dict(model=model, **r))
    return rows


def e3_expected_time(graphs):
    rows = []
    for gname, g, pairs in graphs:
        for w, t in [("rain", "morning_peak"), ("snow", "evening_peak")]:
            gc = apply_conditions(g, w, t, by_class=True, expected="congestion")
            gt = apply_conditions(g, w, t, by_class=True, expected="time")
            diff, route_diff, bad = [], 0, 0
            for s, d in pairs:
                pc, cc, _ = astar(gc, s, d)
                pt, ct, _ = astar(gt, s, d)
                _, cu, _ = ucs(gt, s, d)
                bad += abs(ct - cu) > 1e-9
                diff.append(100 * (ct - cc) / cc)
                route_diff += pc != pt
            rows.append(dict(graph=gname, condition=f"{w}+{t}", pairs=len(pairs),
                             avg_cost_increase_pct=round(st.mean(diff), 2), max_cost_increase_pct=round(max(diff), 2),
                             routes_different=route_diff, routes_different_pct=round(100 * route_diff / len(pairs), 1),
                             ucs_eq_astar=f"{len(pairs) - bad}/{len(pairs)}"))
    return rows


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader(); wr.writerows(rows)


def main():
    os.makedirs(OUT, exist_ok=True)
    loaded = [(name, load(folder), n) for name, folder, n in GRAPHS]
    graphs = [(name, g, sample_pairs(g, n)) for name, g, n in loaded]
    osm, osm_pairs = graphs[2][1], graphs[2][2]
    print(f"OSM graph: {len(osm.nodes)} nodes, {len(osm.edges)} directed edges, {len(osm_pairs)} sampled pairs "
          f"(heuristic speed {osm.max_speed_kmh:.0f} km/h)")
    e1 = e1_search(osm, osm_pairs)
    e2 = e2_routes(osm, osm_pairs)
    e3 = e3_expected_time(graphs)
    write_csv(f"{OUT}/week15_osm_search.csv", e1)
    write_csv(f"{OUT}/week15_osm_routes.csv", e2)
    write_csv(f"{OUT}/week15_expected_time.csv", e3)

    print("\n== E1: UCS vs A* on the OSM graph (road-class model) ==")
    for r in e1:
        print(f"{r['condition']:19} time UCS {r['ucs_nodes_time']:6} A* {r['astar_nodes_time']:6} (-{r['reduction_time_pct']}%) "
              f"| dist UCS {r['ucs_nodes_dist']:6} A* {r['astar_nodes_dist']:6} (-{r['reduction_dist_pct']}%) "
              f"| ms {r['ucs_ms_time']} vs {r['astar_ms_time']} | optimal {r['optimal_same']}")
    print("\n== E2: routes changed vs clear+off_peak on the OSM graph ==")
    for r in e2:
        print(f"{r['model']:10} {r['condition']:19} {r['routes_changed']:4}/{r['pairs']} ({r['routes_changed_pct']:5}%) "
              f"saved avg {r['avg_saved_pct_on_changed']}% max {r['max_saved_pct']}%")
    print("\n== E3: E[t] vs t(E[c]) (road-class model) ==")
    for r in e3:
        print(f"{r['graph']:6} {r['condition']:19} cost +{r['avg_cost_increase_pct']}% (max +{r['max_cost_increase_pct']}%) "
              f"| different route {r['routes_different']}/{r['pairs']} ({r['routes_different_pct']}%) | UCS=A* {r['ucs_eq_astar']}")
    print(f"\nSaved to {OUT}/week15_*.csv")
    return e1, e2, e3


if __name__ == "__main__":
    main()
