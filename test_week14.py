"""test_week14.py - Week XIV tests (same PASS/FAIL style as search.py / traffic.py).

    python3 test_week14.py       # exit code 0 = all passed
    python3 -m pytest -v         # all suites

Covers: road-class congestion model (hand calculations, admissibility,
UCS == A* on all 210 pairs x 9 conditions and on the 64-node graph),
the --road-class CLI option, and experiments C and D.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def app(*args):
    r = subprocess.run([sys.executable, "app.py", *args], cwd=HERE, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def run_tests():
    from graph import Graph
    from search import ucs, astar
    import traffic as T
    import scale_test

    ok = True

    def check(name, cond):
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {name}")
        ok &= bool(cond)

    edge = lambda g, a, b: next(e for e in g.edges if e["src"] == a and e["dst"] == b)
    g = Graph().load(os.path.join(HERE, "nodes.csv"), os.path.join(HERE, "edges.csv"))

    # 1. classes and the "off" switch
    check("road_class: 40 -> local, 50 -> main, 60/70 -> arterial",
          [T.road_class(v) for v in (40, 50, 60, 70)] == ["local", "main", "arterial", "arterial"])
    a, b = T.apply_conditions(g, "snow", "evening_peak"), T.apply_conditions(g, "snow", "evening_peak", by_class=False)
    check("by_class=False is exactly the Week XIII model", [e["time_min"] for e in a.edges] == [e["time_min"] for e in b.edges])

    # 2. Hand case F - arterial road reacts LESS. Zaisan Bypass N05->N11:
    #    base 0.30, 60 km/h -> arterial, k = 0.5, 3.632 km, snow + morning_peak [0.05, 0.30, 0.65]
    #    levels: 0.30 - 0.125 = 0.175 / 0.30 / 0.30 + 0.125 = 0.425
    #    E[c] = 0.05*0.175 + 0.30*0.30 + 0.65*0.425 = 0.00875 + 0.09 + 0.27625 = 0.375
    #    (Week XIII uniform: 0.05*0.05 + 0.30*0.30 + 0.65*0.55 = 0.45)
    #    time = 3.632 / (60 * (1 - 0.7*0.375)) * 60 = 3.632 / 44.25 * 60 = 4.925 -> 4.92 min  (uniform 5.30)
    gc = T.apply_conditions(g, "snow", "morning_peak", by_class=True)
    gu = T.apply_conditions(g, "snow", "morning_peak")
    e, u = edge(gc, "N05", "N11"), edge(gu, "N05", "N11")
    check(f"Hand F: Zaisan Bypass snow+morning E[c] 0.45 -> 0.375, time 5.30 -> 4.92 min (got {e['congestion']}, {e['time_min']})",
          abs(e["congestion"] - 0.375) < 1e-9 and e["time_min"] == 4.92 and abs(u["congestion"] - 0.45) < 1e-9 and u["time_min"] == 5.30)

    # 3. Hand case G - local street reacts MORE. Tokyo Street N12->N13:
    #    base 0.50, 40 km/h -> local, k = 1.5, 2.36 km
    #    levels: 0.50 - 0.375 = 0.125 / 0.50 / 0.50 + 0.375 = 0.875
    #    E[c] = 0.05*0.125 + 0.30*0.50 + 0.65*0.875 = 0.00625 + 0.15 + 0.56875 = 0.725   (uniform 0.65)
    #    time = 2.36 / (40 * (1 - 0.7*0.725)) * 60 = 2.36 / 19.7 * 60 = 7.188 -> 7.19 min
    e = edge(gc, "N12", "N13")
    check(f"Hand G: Tokyo Street snow+morning E[c] 0.65 -> 0.725, time 7.19 min (got {e['congestion']}, {e['time_min']})",
          abs(e["congestion"] - 0.725) < 1e-9 and e["time_min"] == 7.19 and abs(edge(gu, "N12", "N13")["congestion"] - 0.65) < 1e-9)

    # 4. Hand case H - re-routing on the city graph (numbers from apply_conditions, sums by hand):
    #    Railway Station N04 -> Zaisan N05 with --road-class
    #    clear+off_peak : N04-N03-N02-N05 (centre, Peace Ave + Naadam Rd)          = 9.57 min
    #    snow+evening   : N04-N14-N11-N05 (Bayangol, Khan-Uul, Zaisan Bypass)      = 12.57 min
    #                     old centre route under snow+evening                      = 14.73 min
    #    saved = (14.73 - 12.57) / 14.73 = 14.7 %
    off = T.apply_conditions(g, "clear", "off_peak", by_class=True)
    bad = T.apply_conditions(g, "snow", "evening_peak", by_class=True)
    p0, c0, _ = astar(off, "N04", "N05")
    p1, c1, _ = astar(bad, "N04", "N05")
    old = sum(edge(bad, x, y)["time_min"] for x, y in zip(p0, p0[1:]))
    check(f"Hand H: N04->N05 re-routes to the bypass in snow+evening ({c0:.2f} -> {c1:.2f} min, old route {old:.2f})",
          p0 == ["N04", "N03", "N02", "N05"] and p1 == ["N04", "N14", "N11", "N05"]
          and abs(c0 - 9.57) < 1e-9 and abs(c1 - 12.57) < 1e-9 and abs(old - 14.73) < 1e-9)

    # 5. admissibility + optimality with the class model, all 210 pairs x 9 conditions x time/dist
    ids = list(g.nodes)
    pairs = [(s, t) for s in ids for t in ids if s != t]
    total_bad, slack = 0, float("inf")
    for w in T.WEATHER:
        for t in T.TIME:
            gx = T.apply_conditions(g, w, t, by_class=True)
            slack = min(slack, min(x["time_min"] - gx.heuristic_time_min(x["src"], x["dst"]) for x in gx.edges))
            for cost in ("time", "dist"):
                for s, d in pairs:
                    pu, cu, _ = ucs(gx, s, d, cost)
                    pa, ca, _ = astar(gx, s, d, cost)
                    total_bad += (pu is None) != (pa is None) or abs(cu - ca) > 1e-9
    check(f"Road-class model: UCS == A* on {len(pairs)} pairs x 9 conditions x time/dist (mismatches {total_bad}), "
          f"heuristic consistent (min slack {slack:.2f} min)", len(pairs) == 210 and total_bad == 0 and slack >= 0)

    # 6. same on the 64-node graph
    folder = os.path.join(HERE, "data_scale")
    if not os.path.exists(os.path.join(folder, "edges.csv")):
        scale_test.generate(folder)
    gs = Graph().load(os.path.join(folder, "nodes.csv"), os.path.join(folder, "edges.csv"))
    m = scale_test.measure(T.apply_conditions(gs, "snow", "evening_peak", by_class=True))
    check(f"Road-class model, 64 nodes snow+evening: UCS == A* on {m['pairs']} pairs x time/dist",
          m["time"]["mismatches"] == 0 and m["dist"]["mismatches"] == 0)

    # 7. CLI
    _, o1, _ = app("--from", "N04", "--to", "N05", "--weather", "clear", "--time", "off-peak", "--road-class")
    _, o2, _ = app("--from", "N04", "--to", "N05", "--weather", "snow", "--time", "evening", "peak", "--road-class")
    r1, r2 = re.search(r"Route : (.*)", o1).group(1), re.search(r"Route : (.*)", o2).group(1)
    check(f"CLI --road-class: route changes ({r1.count('->') + 1} stops -> via Zaisan Bypass)",
          "road-class model" in o2 and "Ard Cinema" in r1 and "Khan-Uul District" in r2 and "12.57 min" in o2)
    rc, _, err = app("--from", "N04", "--to", "N05", "--road-class")
    check("CLI --road-class without --weather/--time is a usage error", rc == 2 and "road-class" in err)

    # 8. experiments C and D
    cwd = os.getcwd()
    os.chdir(HERE)
    try:
        import experiments
        bc = experiments.bayes_check()
        drows = experiments.route_model_experiment()
    finally:
        os.chdir(cwd)
    check(f"Experiment C: hand == BN on {len(bc)} queries, sampling error < 0.03",
          all(float(r["hand_minus_bn"]) < 1e-12 and r["sampling_mean_abs_err"] < 0.03 for r in bc))
    ref_zero = all(r["routes_changed"] == 0 for r in drows if r["condition"] == "clear+off_peak")
    opt = all(r["ucs_eq_astar"].split("/")[0] == r["ucs_eq_astar"].split("/")[1] for r in drows)
    nonneg = all(r["avg_saved_pct_on_changed"] >= 0 for r in drows)
    more = all(next(x["routes_changed"] for x in drows if x["graph"] == r["graph"] and x["condition"] == r["condition"]
                    and x["model"] == "road_class") >= r["routes_changed"] for r in drows if r["model"] == "uniform")
    check("Experiment D: 0 changes at reference, re-routing never slower, road-class >= uniform, UCS == A*",
          ref_zero and opt and nonneg and more)

    print("\nALL TESTS PASSED" if ok else "\nSOME TESTS FAILED")
    return ok


def test_week14():  # pytest entry point
    cwd = os.getcwd()
    os.chdir(HERE)
    try:
        assert run_tests()
    finally:
        os.chdir(cwd)


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)
