"""test_week15.py - Week XV tests (same PASS/FAIL style as search.py / traffic.py).

    python3 test_week15.py       # exit code 0 = all passed
    python3 -m pytest -v         # all suites

Covers: heuristic speed / measured-length safety in graph.py, expected travel
time E[t] (hand calculation, Jensen, optimality), OSM road classes, the real
OpenStreetMap graph (consistency + UCS == A*), calibrate.py and the new CLI
options (--expected-time, --k-file, --roads).
"""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def app(*args):
    r = subprocess.run([sys.executable, "app.py", *args], cwd=HERE, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def cost_of(out):
    return float(re.search(r"Cost  : ([\d.]+) min", out).group(1))


def run_tests():
    from graph import Graph, haversine_km
    from search import ucs, astar
    import traffic as T
    import calibrate as C
    import experiments_week15 as X

    ok = True

    def check(name, cond):
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {name}")
        ok &= bool(cond)

    edge = lambda g, a, b: next(e for e in g.edges if e["src"] == a and e["dst"] == b)
    g = Graph().load(os.path.join(HERE, "nodes.csv"), os.path.join(HERE, "edges.csv"))
    ids = list(g.nodes)
    pairs = [(s, t) for s in ids for t in ids if s != t]

    # 1. graph.py safety changes do not touch the city graph
    check("City graph: heuristic speed 70 km/h, times rounded to nearest (Week XII numbers unchanged)",
          g.max_speed_kmh == 70 and not g.ceil_time and edge(g, "N01", "N02")["time_min"] == 4.30)

    # 2. a road faster than 70 km/h raises the heuristic speed -> A* stays optimal
    with tempfile.TemporaryDirectory() as d:
        open(f"{d}/nodes.csv", "w").write("id,name,lat,lon\nA,A,47.90,106.80\nB,B,47.90,106.90\nC,C,47.95,106.85\n")
        open(f"{d}/edges.csv", "w").write(
            "from,to,road,speed_limit_kmh,oneway,base_congestion,blocked\n"
            "A,B,Motorway,110,0,0.0,0\nA,C,Street,40,0,0.0,0\nC,B,Street,40,0,0.0,0\n")
        gf = Graph().load(f"{d}/nodes.csv", f"{d}/edges.csv")
    slack = min(e["time_min"] - gf.heuristic_time_min(e["src"], e["dst"]) for e in gf.edges)
    check(f"Fast road (110 km/h): heuristic speed {gf.max_speed_kmh:.0f}, consistent (slack {slack:.2f}), UCS == A*",
          gf.max_speed_kmh == 110 and slack >= 0 and abs(ucs(gf, "A", "B")[1] - astar(gf, "A", "B")[1]) < 1e-9)

    # 3. road class from the OSM highway tag
    check("road_class uses the OSM tag: trunk -> arterial, primary_link -> main, tertiary -> local",
          T.road_class(40, "trunk") == "arterial" and T.road_class(70, "primary_link") == "main"
          and T.road_class(60, "tertiary") == "local" and T.road_class(60, "") == "arterial")

    # 4. Hand case I - expected travel time. Peace Avenue N01->N02, 1.463 km, 40 km/h,
    #    base 0.70, snow + morning_peak [0.05, 0.30, 0.65], uniform model:
    #    c = 0.45 : 1.463 / (40 * 0.685) * 60 = 3.2036 min
    #    c = 0.70 : 1.463 / (40 * 0.510) * 60 = 4.3029 min
    #    c = 0.95 : 1.463 / (40 * 0.335) * 60 = 6.5507 min
    #    E[t] = 0.05*3.2036 + 0.30*4.3029 + 0.65*6.5507 = 0.1602 + 1.2909 + 4.2580 = 5.709 -> 5.71 min
    #    t(E[c]) = t(0.85) = 5.42 min (hand case D)  ->  E[t] is 0.29 min (5.4%) higher
    ge = T.apply_conditions(g, "snow", "morning_peak", expected="time")
    gc = T.apply_conditions(g, "snow", "morning_peak")
    check(f"Hand I: N01->N02 snow+morning E[t] = 5.71 min vs t(E[c]) = 5.42 min (got {edge(ge, 'N01', 'N02')['time_min']})",
          edge(ge, "N01", "N02")["time_min"] == 5.71 and edge(gc, "N01", "N02")["time_min"] == 5.42)

    # 5. Jensen: E[t] >= t(E[c]) on every edge; admissible; UCS == A* on 210 pairs x 9 conditions
    jensen, slack, bad = True, float("inf"), 0
    for w in T.WEATHER:
        for t in T.TIME:
            a = T.apply_conditions(g, w, t, by_class=True, expected="time")
            b = T.apply_conditions(g, w, t, by_class=True)
            jensen &= all(x["time_min"] >= y["time_min"] - 0.01 for x, y in zip(a.edges, b.edges))
            slack = min(slack, min(e["time_min"] - a.heuristic_time_min(e["src"], e["dst"]) for e in a.edges))
            for s, d in pairs:
                bad += abs(ucs(a, s, d)[1] - astar(a, s, d)[1]) > 1e-9
    check(f"E[t] >= t(E[c]) on every edge; consistent (slack {slack:.2f}); UCS == A* on 210 pairs x 9 conditions "
          f"(mismatches {bad})", jensen and slack >= 0 and bad == 0)

    # 6. the real OpenStreetMap graph
    folder = os.path.join(HERE, "data_osm")
    go = Graph().load(os.path.join(folder, "nodes.csv"), os.path.join(folder, "edges.csv"))
    raw = open(os.path.join(HERE, "data_osm_raw", "ub_tertiary.osm"), encoding="utf-8").read(2000)
    short = sum(e["distance_km"] < haversine_km(*go.nodes[e["src"]][1:], *go.nodes[e["dst"]][1:]) for e in go.edges)
    check(f"OSM graph: {len(go.nodes)} nodes, {len(go.edges)} directed edges, ODbL source note kept, "
          f"no edge shorter than the straight line ({short})",
          len(go.nodes) > 1000 and go.ceil_time and "ODbL" in raw and short == 0)
    worst = float("inf")
    for w, t, mode in [("clear", "off_peak", "congestion"), ("snow", "evening_peak", "congestion"),
                       ("snow", "evening_peak", "time")]:
        gx = T.apply_conditions(go, w, t, by_class=True, expected=mode)
        worst = min(worst, min(e["time_min"] - gx.heuristic_time_min(e["src"], e["dst"]) for e in gx.edges))
    check(f"OSM graph: heuristic consistent on every edge under 3 settings (min slack {worst:.4f} min)", worst >= 0)
    osm_pairs = X.sample_pairs(go, 150, seed=7)
    gx = T.apply_conditions(go, "snow", "evening_peak", by_class=True, expected="time")
    bad = sum((ucs(gx, s, d, c)[0] is None) != (astar(gx, s, d, c)[0] is None)
              or abs(ucs(gx, s, d, c)[1] - astar(gx, s, d, c)[1]) > 1e-9 for s, d in osm_pairs for c in ("time", "dist"))
    check(f"OSM graph: UCS == A* on {len(osm_pairs)} random pairs x time/dist (snow+evening, road class, E[t]); "
          f"mismatches {bad}", bad == 0)

    # 7. calibration: exact recovery without noise, file round trip, never worse than uniform
    true_k = {"local": 1.75, "main": 1.0, "arterial": 0.5}
    trips = C.make_synthetic_trips(g, true_k, n=30, noise=0.0, seed=3)
    k, e = C.fit(g, trips)
    check(f"Calibration recovers k exactly from 30 noise-free synthetic trips (got {k}, RMSE {e['rmse']:.3f})",
          k == true_k and e["rmse"] < 1e-9)
    with tempfile.TemporaryDirectory() as d:
        C.write_trips(f"{d}/t.csv", trips)
        back = C.read_trips(f"{d}/t.csv")
    noisy = C.make_synthetic_trips(g, true_k, n=30, noise=0.05, seed=4)
    rows = C.report(g, noisy)
    check("Trips CSV round trip; fitted RMSE <= uniform and guess RMSE on noisy trips",
          [(t["src"], t["dst"], t["observed"]) for t in back] == [(t["src"], t["dst"], t["observed"]) for t in trips]
          and all(rows[0][2]["rmse"] <= r[2]["rmse"] + 1e-12 for r in rows[1:]))

    # 8. CLI
    base = ["--from", "N01", "--to", "N15", "--weather", "snow", "--time", "evening", "peak", "--road-class"]
    _, o1, _ = app(*base)
    _, o2, _ = app(*base, "--expected-time")
    check(f"CLI --expected-time raises the cost ({cost_of(o1)} -> {cost_of(o2)} min)",
          cost_of(o2) > cost_of(o1) and "E[travel time]" in o2)
    with tempfile.TemporaryDirectory() as d:
        json.dump({"k": {"local": 1.5, "main": 1.0, "arterial": 0.5}}, open(f"{d}/k.json", "w"))
        _, o3, _ = app(*base[:-1], "--k-file", f"{d}/k.json")
    check("CLI --k-file with the Week XIV guess gives the same cost as --road-class", cost_of(o3) == cost_of(o1))
    rc, _, err = app("--from", "N01", "--to", "N15", "--expected-time")
    check("CLI --expected-time without --weather/--time is a usage error", rc == 2 and "expected-time" in err)
    _, o4, _ = app("--data", "data_osm", "--from", "N0674", "--to", "N1275", "--weather", "snow", "--time",
                   "evening", "peak", "--road-class", "--roads")
    check("CLI --roads on the OSM graph lists named roads (Peace Bridge on the snow route)",
          "Roads : " in o4 and "Peace Bridge" in o4)

    print("\nALL TESTS PASSED" if ok else "\nSOME TESTS FAILED")
    return ok


def test_week15():  # pytest entry point
    cwd = os.getcwd()
    os.chdir(HERE)
    try:
        assert run_tests()
    finally:
        os.chdir(cwd)


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)
