"""test_ub_graph.py - checks for the accurate Ulaanbaatar station graph (data_ub/).

    python3 test_ub_graph.py
    python3 -m pytest -v

The graph is built by make_ub_graph.py from OpenStreetMap data (ODbL).
"""
import csv
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
UB = os.path.join(HERE, "data_ub")


def run_tests():
    from graph import Graph, haversine_km
    from search import astar, ucs
    import make_ub_graph as M
    import traffic as T

    ok = True

    def check(name, cond):
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {name}")
        ok &= bool(cond)

    g = Graph().load(os.path.join(UB, "nodes.csv"), os.path.join(UB, "edges.csv"))
    st = list(csv.DictReader(open(os.path.join(UB, "stations.csv"), encoding="utf-8")))
    names = [n for n, _, _ in g.nodes.values()]
    byname = {n: i for i, (n, _, _) in g.nodes.items()}

    # 1. size, names, area
    inside = all(47.80 <= la <= 48.00 and 106.65 <= lo <= 107.15 for _, la, lo in g.nodes.values())
    check(f"{len(g.nodes)} stations, {len(g.edges)} directed road links, unique names, all inside Ulaanbaatar",
          len(g.nodes) >= 45 and len(set(names)) == len(names) and inside)

    # 2. every station position comes from OpenStreetMap (re-resolved from the downloaded data)
    places = M.load_places()
    spec = {name: (terms, keys) for name, _, terms, keys in M.STATION_SPEC}
    worst = 0.0
    for r in st:
        if r["osm_feature"].startswith("road:"):
            continue  # bridges come from the road data
        p, _ = M.find_place(places, *spec[r["name"]])
        worst = max(worst, haversine_km(float(r["place_lat"]), float(r["place_lon"]), p["lat"], p["lon"]))
    junction_ok = all(haversine_km(float(r["junction_lat"]), float(r["junction_lon"]), *g.nodes[r["id"]][1:]) < 0.001
                      and abs(haversine_km(float(r["place_lat"]), float(r["place_lon"]), *g.nodes[r["id"]][1:])
                              - float(r["snap_km"])) < 0.002 for r in st)
    check(f"Place coordinates = OSM feature coordinates (max difference {worst * 1000:.2f} m); node = serving road "
          f"junction; "
          f"every station has an OSM reference and a road within {M.SNAP_MAX_KM * 1000:.0f} m "
          f"({M.SNAP_MAX_AREA_KM * 1000:.0f} m for airport/park areas)",
          worst < 0.001 and junction_ok and all(r["osm_feature"] for r in st)
          and all(float(r["snap_km"]) <= M.snap_limit(r["kind"], r["osm_feature"]) for r in st))

    # 3. links follow real roads
    geo = {}
    for r in csv.DictReader(open(os.path.join(UB, "geometry.csv"), encoding="utf-8")):
        geo[(r["from"], r["to"])] = [tuple(map(float, p.split())) for p in r["points"].split(";")]
    lim = {r["id"]: M.snap_limit(r["kind"], r["osm_feature"]) for r in st}
    short, bad_geo, bad_len = 0, 0, 0
    for e in g.edges:
        (_, la, lo), (_, lb, lob) = g.nodes[e["src"]], g.nodes[e["dst"]]
        short += e["distance_km"] < haversine_km(la, lo, lb, lob)
        pts = geo.get((e["src"], e["dst"]))
        if not pts:
            bad_geo += 1
            continue
        poly = sum(haversine_km(*a, *b) for a, b in zip(pts, pts[1:]))
        bad_len += not (0.97 * e["distance_km"] - 0.01 <= poly <= e["distance_km"] + 0.01)
        bad_geo += haversine_km(*pts[0], la, lo) > 0.001 or haversine_km(*pts[-1], lb, lob) > 0.001
    check(f"Every link has the full street shape (OSM shape points), starts/ends at its stations, length within 3% "
          f"(missing/bad {bad_geo}, length mismatch {bad_len}, shorter than straight line {short})",
          bad_geo == 0 and bad_len == 0 and short == 0)

    # 4. strongly connected
    ids = list(g.nodes)
    unreach = sum(1 for s in ids for t in ids if s != t and ucs(g, s, t, "dist")[0] is None)
    check(f"Every station can reach every other station (unreachable pairs: {unreach})", unreach == 0)

    # 5. heuristic consistent + UCS == A* on all pairs, several settings
    pairs = [(s, t) for s in ids for t in ids if s != t]
    settings = [(None, None, False, "congestion"), ("clear", "off_peak", True, "congestion"),
                ("snow", "evening_peak", True, "congestion"), ("rain", "morning_peak", True, "time")]
    bad, slack = 0, float("inf")
    for w, t, cls, exp in settings:
        gx = g if w is None else T.apply_conditions(g, w, t, by_class=cls, expected=exp)
        slack = min(slack, min(e["time_min"] - gx.heuristic_time_min(e["src"], e["dst"]) for e in gx.edges))
        for cost in ("time", "dist"):
            for s, d in pairs:
                bad += abs(ucs(gx, s, d, cost)[1] - astar(gx, s, d, cost)[1]) > 1e-9
    check(f"UCS == A* on all {len(pairs)} pairs x time/dist x {len(settings)} settings (mismatches {bad}); "
          f"heuristic consistent (min slack {slack:.3f} min)", bad == 0 and slack >= 0)

    # 6. real-world sanity
    pos = lambda n: g.nodes[byname[n]][1:]
    sq = pos("Sukhbaatar Square")
    checks = [pos("Zaisan Memorial")[0] < sq[0], pos("Narantuul Market")[1] > sq[1],
              pos("Buyant-Ukhaa Airport")[0] < sq[0] and pos("Buyant-Ukhaa Airport")[1] < sq[1],
              pos("Ulaanbaatar Railway Station")[1] < sq[1], pos("Dambadarjaa")[0] > sq[0]]
    _, d_air, _ = ucs(g, byname["Sukhbaatar Square"], byname["Buyant-Ukhaa Airport"], "dist")
    check(f"Geography: Zaisan south, Narantuul east, airport south-west, railway west, Dambadarjaa north of the "
          f"square; Sukhbaatar Square -> airport by road {d_air:.1f} km (expected 15-25 km)",
          all(checks) and 15 <= d_air <= 25)

    # 7. the app runs on it
    r = subprocess.run([sys.executable, "app.py", "--data", "data_ub", "--from", byname["Sukhbaatar Square"],
                        "--to", byname["Buyant-Ukhaa Airport"], "--compare", "--weather", "snow", "--time",
                        "evening", "peak", "--road-class"], cwd=HERE, capture_output=True, text=True)
    check("app.py --data data_ub: Sukhbaatar Square -> Buyant-Ukhaa Airport works, UCS == A*",
          r.returncode == 0 and "Same optimal cost: yes" in r.stdout and "Buyant-Ukhaa Airport" in r.stdout)

    print("\nALL TESTS PASSED" if ok else "\nSOME TESTS FAILED")
    return ok


def test_ub_graph():  # pytest entry point
    cwd = os.getcwd()
    os.chdir(HERE)
    try:
        assert run_tests()
    finally:
        os.chdir(cwd)


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)
