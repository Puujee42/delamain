"""test_visualizer.py - tests for visualizer.py (headless, matplotlib Agg; no window).

    python3 test_visualizer.py
    python3 -m pytest -v
"""
import os
import random
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def run_tests():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import visualizer as V
    import traffic as T
    from search import astar, ucs

    ok = True

    def check(name, cond):
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {name}")
        ok &= bool(cond)

    model = V.Model()

    # 1. the expansion recorder sees exactly what search.py counts, and does not change results
    g = model.graph("city")
    same = True
    for s, t in [("N01", "N15"), ("N09", "N06"), ("N04", "N05"), ("N03", "N13")]:
        for fn in (ucs, astar):
            r = V.run_search(fn, g, s, t, "time")
            p, c, n = fn(g, s, t, "time")
            same &= r["path"] == p and r["cost"] == c and r["expanded"] == n == len(r["expanded_nodes"])
    check("Recorder: expanded node list length == search.py count, same path and cost", same)

    # 2. the summary agrees with app.py numbers (Week XIV hand case H)
    st = dict(V.default_state("city"), weather="snow", time="evening_peak", road_class=True, src="N04", dst="N05")
    res = model.compute(st)
    txt = V.summary_text(st, res)
    check("Summary: N04->N05 snow+evening road-class = 12.57 min via Bayangol, Khan-Uul, UCS == A*",
          "12.57 min" in txt and "Bayangol -> Khan-Uul District -> Zaisan" in txt and "same optimal cost: YES" in txt)

    # 3. Hand case J - diagnostic reasoning shown in the BN tab.
    #    P(W | T=morning_peak, C=high) ~ P(W) * P(high | W, morning):
    #      clear 0.70*0.40 = 0.28, snow 0.15*0.65 = 0.0975, rain 0.15*0.50 = 0.075, sum 0.4525
    #      -> clear 0.6188, snow 0.2155, rain 0.1657
    post, ev = V.bn_marginals(dict(V.default_state(), time="morning_peak", congestion="high"))
    hand = {"clear": 0.28 / 0.4525, "snow": 0.0975 / 0.4525, "rain": 0.075 / 0.4525}
    check("Hand J: P(W | morning peak, C=high) = 0.619 / 0.215 / 0.166, observed nodes one-hot",
          all(abs(post["weather"][w] - hand[w]) < 1e-12 for w in hand)
          and post["time"]["morning_peak"] == 1.0 and post["congestion"]["high"] == 1.0)

    # 4. sampling agrees with exact inference (predictive and diagnostic) and the query choice is sensible
    rng = random.Random(5)
    q1, e1 = V.query_of(dict(V.default_state(), weather="snow", time="evening_peak"))
    q2, e2 = V.query_of(dict(V.default_state(), time="morning_peak", congestion="high"))
    q3, e3 = V.query_of(dict(V.default_state(), weather="snow", time="evening_peak", congestion="high"))
    err = max(max(abs(v - T.posterior(q, e)[k]) for k, v in V.sample_dist(q, e, 20000, rng).items())
              for q, e in [(q1, e1), (q2, e2)])
    check(f"Sampling vs exact (20000 samples, predictive + diagnostic): max error {err:.4f} < 0.02",
          err < 0.02 and (q1, q2, q3) == ("congestion", "weather", "congestion") and "congestion" not in e3)

    # 5. all four views draw on all three graphs; Checks tab passes
    drawn, all_pass = 0, True
    for gname in ("city", "scale", "osm"):
        st = dict(V.default_state(gname), weather="rain", time="morning_peak", road_class=True, samples=500)
        res = model.compute(st)
        for fn in (lambda f: V.draw_map(f, st, res), lambda f: V.draw_bn(f, st), lambda f: V.draw_cpd(f, st)):
            fig = plt.figure(); fn(fig); fig.canvas.draw(); plt.close(fig); drawn += 1
        fig = plt.figure()
        ck = V.draw_checks(fig, model, st, V.checks(model, st, pairs=60))
        fig.canvas.draw(); plt.close(fig); drawn += 1
        all_pass &= ck["bad"] == 0 and ck["sums_ok"]
    check(f"All 4 views drawn on city, 64-node and OSM graphs ({drawn} figures); UCS == A* in Checks", drawn == 12 and all_pass)

    # 6. step-by-step tracer == search.py on every pair (city graph, plain and snow+evening road-class)
    import viz_trace as VT
    import viz_tabs as VB
    gc = T.apply_conditions(g, "snow", "evening_peak", by_class=True)
    ids = list(g.nodes)
    runs = bad = 0
    for gg in (g, gc):
        for s_ in ids:
            for t_ in ids:
                if s_ == t_:
                    continue
                for cost in ("time", "dist"):
                    for algo, fn in (("ucs", ucs), ("astar", astar)):
                        p_, c_, x_ = fn(gg, s_, t_, cost)
                        tr = VT.run_trace(gg, s_, t_, cost, algo)
                        runs += 1
                        bad += not (tr.path == p_ and tr.cost == c_ and tr.expanded == x_)
    check(f"Tracer == search.py (path, cost, expanded) on {runs} runs (mismatches {bad})", runs == 1680 and bad == 0)

    # 7. the highlighted code lines are the right ones in search.py
    okl = True
    for algo in ("ucs", "astar"):
        src, first, idx = VT.code_lines(algo)
        okl &= "heappush" in src[idx["push"]] and "heappop" in src[idx["pop"]] and "nc = c + w" in src[idx["relax"]]
    check("Code view: push / pop / relax events point at the matching lines of search.py", okl)

    # 8. Hand case K - the Route tab explanation of one road.
    #    N04 -> N14 Peace Avenue, 1.757 km, 50 km/h (main, k=1), base 0.50, snow + evening [0.03, 0.22, 0.75]
    #    c(level) = 0.25 / 0.50 / 0.75;  E[c] = 0.03*0.25 + 0.22*0.50 + 0.75*0.75 = 0.0075 + 0.11 + 0.5625 = 0.68
    #    time = 1.757 / (50 * (1 - 0.7*0.68)) * 60 = 1.757 / 26.2 * 60 = 4.024 -> 4.02 min
    st = dict(V.default_state("city"), weather="snow", time="evening_peak", road_class=True, src="N04", dst="N05")
    res = model.compute(st)
    segs = VT.route_segments(res["g"], res["base"], res["astar"]["path"])
    text, used = VT.explain_edge(segs[0], st)
    check(f"Hand K: segment 1 N04->N14 E[c] = 0.68 -> 4.02 min; segment minutes add up to the route cost "
          f"({sum(x['minutes'] for x in segs):.2f})",
          "E[c] = 0.03*0.250 + 0.22*0.500 + 0.75*0.750 = 0.6800" in text and "= 4.02 min" in text
          and abs(sum(x["minutes"] for x in segs) - res["astar"]["cost"]) < 1e-9
          and used[-1] == "Graph.travel_time_min")

    # 9. pipeline shows what is used; every method has its key line found in the source
    pl = {m: act for _, m, act, _ in VT.pipeline(dict(st, expected_time=True))}
    keys_ok = all(any(k for _, k in VB.method_listing(m)[1]) for m in VT.METHODS if m in VB.KEY_LINES)
    check("Pipeline: road class + E[t] on, E[c] off; every method view highlights its key line",
          pl["traffic.edge_congestion"] and pl["traffic.expected_edge_time"]
          and not pl["traffic.expected_edge_congestion"] and keys_ok)

    # 10. route and step views draw on all three graphs
    n = 0
    for gname in ("city", "scale", "osm"):
        st2 = dict(V.default_state(gname), weather="rain", time="morning_peak", road_class=True)
        r2 = model.compute(st2)
        sg = VT.route_segments(r2["g"], r2["base"], r2["astar"]["path"])
        fig = plt.figure(); VB.draw_route(fig, st2, r2, sg, VB.default_selected(sg)); fig.canvas.draw(); plt.close(fig)
        fig = plt.figure(); fin = VB.draw_trace_final(fig, r2["g"], st2); fig.canvas.draw(); plt.close(fig)
        n += fin["astar"].cost == r2["astar"]["cost"] and fin["astar"].steps < fin["ucs"].steps
    check(f"Route + step views drawn on 3 graphs; A* finishes in fewer steps than UCS on {n}/3", n == 3)

    # 11. snapshot mode writes the 6 PNGs
    with tempfile.TemporaryDirectory() as d:
        import io
        from contextlib import redirect_stdout
        with redirect_stdout(io.StringIO()):
            files = V.snapshot(dict(V.default_state("city"), weather="snow", time="morning_peak"), d)
        sizes = [os.path.getsize(f) for f in files]
    check(f"--snapshot writes 6 PNG files ({', '.join(os.path.basename(f) for f in files)})",
          len(files) == 6 and all(s > 10000 for s in sizes))

    print("\nALL TESTS PASSED" if ok else "\nSOME TESTS FAILED")
    return ok


def test_visualizer():  # pytest entry point
    cwd = os.getcwd()
    os.chdir(HERE)
    try:
        assert run_tests()
    finally:
        os.chdir(cwd)


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)
