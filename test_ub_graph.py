"""test_ub_graph.py - checks for the accurate Ulaanbaatar graphs (4 levels).

    small   data_ub/       53 landmarks                      (station graph, links = real roads)
    medium  data_ub_m/     + other named OSM places          (station graph)
    large   data_ub_l/     + named bus stops                 (station graph)
    full    data_ub_full/  every street junction + ~540 stations (exact street graph)

    python3 test_ub_graph.py
    python3 -m pytest -v

The graphs are built by make_ub_graph.py from OpenStreetMap data (ODbL).
"""
import csv
import json
import os
import random
import subprocess
import sys
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
MIN_STATIONS = {"small": 45, "medium": 100, "large": 200, "full": 400}


def reach(g, start, reverse=False):
    adj = {}
    for e in g.edges:
        a, b = (e["dst"], e["src"]) if reverse else (e["src"], e["dst"])
        adj.setdefault(a, []).append(b)
    seen, q = {start}, deque([start])
    while q:
        for v in adj.get(q.popleft(), []):
            if v not in seen:
                seen.add(v); q.append(v)
    return seen


def chain_on(gf, geo_rows, path, at):
    """A station-graph route as the chain of full-graph junctions along its street shapes."""
    chain = []
    for a, b in zip(path, path[1:]):
        for la, lo in geo_rows[(a, b)]:
            n = at.get((round(la, 6), round(lo, 6)))
            if n and (not chain or chain[-1] != n):
                chain.append(n)
    return chain


def check_level(level, check, landmarks_ref):
    from graph import Graph, haversine_km
    from search import astar, ucs
    import make_ub_graph as M
    import traffic as T

    full = level == "full"
    folder = os.path.join(HERE, M.LEVELS[level])
    g = Graph().load(os.path.join(folder, "nodes.csv"), os.path.join(folder, "edges.csv"))
    st = list(csv.DictReader(open(os.path.join(folder, "stations.csv"), encoding="utf-8")))
    st_ids = [r["id"] for r in st]
    names = [g.nodes[i][0] for i in st_ids]
    byname = {g.nodes[i][0]: i for i in st_ids}
    tag = f"[{level}]"

    # 1. size, names, area
    # (the full street graph also has junctions where streets continue past the download box)
    inside = all(47.80 <= g.nodes[i][1] <= 48.00 and 106.65 <= g.nodes[i][2] <= 107.15 for i in st_ids)
    kinds = {}
    for r in st:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    check(f"{tag} {len(st)} stations ({sum(r['id'].startswith('B') for r in st)} bus stops, {len(kinds)} kinds) on "
          f"{len(g.nodes)} nodes, {len(g.edges)} directed road links; unique station names; all inside Ulaanbaatar",
          len(st) >= MIN_STATIONS[level] and len(set(names)) == len(names) and inside
          and (full or len(st) == len(g.nodes)))

    # 2. every station position comes from OpenStreetMap (re-checked against the downloaded files)
    places = M.load_places()
    by_ref = {p["ref"]: p for p in places}
    if full:
        by_ref.update({p["ref"]: p for p in M.load_places(M.PLACES_MORE)})
    stops = {f"node/{e['id']}": e for e in json.load(open(M.STOPS, encoding="utf-8"))["elements"]}
    spec = {name: (terms, keys) for name, _, terms, keys in M.STATION_SPEC}
    worst = 0.0
    for r in st:
        la, lo = float(r["place_lat"]), float(r["place_lon"])
        if r["id"].startswith("U"):
            if r["osm_feature"].startswith("road:"):
                continue  # Peace Bridge comes from the road data
            p, _ = M.find_place(places, *spec[r["name"]])
            worst = max(worst, haversine_km(la, lo, p["lat"], p["lon"]))
        elif r["id"].startswith("P"):
            p = by_ref[r["osm_feature"]]
            worst = max(worst, haversine_km(la, lo, p["lat"], p["lon"]))
        else:  # bus stop: mean of same-name stops on both sides of the road (each within 400 m)
            for ref in r["osm_feature"].split("+"):
                worst = max(worst, max(0.0, haversine_km(la, lo, stops[ref]["lat"], stops[ref]["lon"]) - 0.4))
    junction_ok = all(haversine_km(float(r["junction_lat"]), float(r["junction_lon"]), *g.nodes[r["id"]][1:]) < 0.001
                      for r in st)
    check(f"{tag} positions come from OSM features (max deviation {worst * 1000:.2f} m); node = serving road junction",
          worst < 0.001 and junction_ok)

    # 3. links follow real roads; traffic-light waits are part of the time
    geo = {}
    for r in csv.DictReader(open(os.path.join(folder, "geometry.csv"), encoding="utf-8")):
        geo[(r["from"], r["to"])] = [tuple(map(float, p.split())) for p in r["points"].split(";")]
    for (a, b), pts in list(geo.items()):  # full level stores two-way streets once
        geo.setdefault((b, a), pts[::-1])
    short = bad_geo = bad_len = bad_wait = lights = 0
    for e in g.edges:
        (_, la, lo), (_, lb, lob) = g.nodes[e["src"]], g.nodes[e["dst"]]
        short += e["distance_km"] < haversine_km(la, lo, lb, lob)
        lights += e["signals"]
        drive = Graph.travel_time_min(e["distance_km"], e["speed_kmh"], e["congestion"])
        bad_wait += e["time_min"] < drive + Graph.signal_delay_min(e["signals"], e["congestion"]) - 1e-9
        pts = geo.get((e["src"], e["dst"]))
        if not pts:
            bad_geo += 1
            continue
        poly = sum(haversine_km(*a, *b) for a, b in zip(pts, pts[1:]))
        bad_len += not (0.97 * e["distance_km"] - 0.01 <= poly <= e["distance_km"] + 0.01)
        bad_geo += haversine_km(*pts[0], la, lo) > 0.001 or haversine_km(*pts[-1], lb, lob) > 0.001
    check(f"{tag} every link has its full street shape and real length (bad shape {bad_geo}, length mismatch "
          f"{bad_len}, shorter than straight line {short}); {lights:.0f} light passages, each wait included (bad {bad_wait})",
          bad_geo == 0 and bad_len == 0 and short == 0 and bad_wait == 0 and lights > 0)

    # 4. strongly connected (forward and backward search from one node reach all)
    s0 = next(iter(g.nodes))
    check(f"{tag} every node can reach every other one",
          len(reach(g, s0)) == len(g.nodes) == len(reach(g, s0, reverse=True)))

    # 5. heuristic consistent + UCS == A* (all pairs on small, random station pairs otherwise)
    rng = random.Random(7)
    if level == "small":
        pairs = [(s, t) for s in st_ids for t in st_ids if s != t]
    else:  # 40 (full: 20) random start stations x 10 (full: 5) random destination stations
        ns, nt = (20, 5) if full else (40, 10)
        pairs = [(s, t) for s in rng.sample(st_ids, ns) for t in rng.sample([x for x in st_ids if x != s], nt)]
    settings = [(None, None, False, "congestion"), ("clear", "off_peak", True, "congestion"),
                ("snow", "evening_peak", True, "congestion"), ("rain", "morning_peak", True, "time")]
    if full:
        settings = [settings[0], settings[2], settings[3]]
    bad, slack, nu, na, cond = 0, float("inf"), 0, 0, {}
    for w, t, cls, exp in settings:
        gx = g if w is None else T.apply_conditions(g, w, t, by_class=cls, expected=exp)
        cond[(w, t)] = gx
        slack = min(slack, min(e["time_min"] - gx.heuristic_time_min(e["src"], e["dst"]) for e in gx.edges))
        for cost in (("time", "dist") if (not full or w is None) else ("time",)):
            for s, d in pairs:
                pu, cu, xu = ucs(gx, s, d, cost)
                pa, ca, xa = astar(gx, s, d, cost)
                bad += abs(cu - ca) > 1e-9
                if w is None and cost == "time":
                    nu += xu; na += xa
    check(f"{tag} UCS == A* on {len(pairs)} pairs x {len(settings)} settings (mismatches {bad}); "
          f"heuristic consistent (slack {slack:.4f} min); A* expands {100 * (1 - na / nu):.0f}% fewer nodes",
          bad == 0 and slack >= 0)

    if full:
        # 5a. ALT landmarks: consistent for random goals on every street piece (snow), and a better A*
        gs = cond[("snow", "evening_peak")]
        worst = float("inf")
        for t in rng.sample(list(g.nodes), 5):
            worst = min(worst, min(e["time_min"] + gs.heuristic_time_min(e["dst"], t) - gs.heuristic_time_min(e["src"], t)
                                   for e in gs.edges))
        plain = Graph().load(os.path.join(folder, "nodes.csv"), os.path.join(folder, "edges.csv"))
        del plain.alt_idx
        ps = T.apply_conditions(plain, "snow", "evening_peak", by_class=True)
        n_alt = n_line = same = 0
        for a, b in pairs[:40]:
            pa, ca, xa = astar(gs, a, b)
            pp, cp, xp = astar(ps, a, b)
            n_alt += xa; n_line += xp; same += abs(ca - cp) < 1e-9
        check(f"{tag} ALT landmarks ({len(g.alt_from)}): heuristic consistent on all {len(gs.edges)} pieces x 5 goals "
              f"(min slack {worst:.4f}); same optimal cost; {100 * (1 - n_alt / n_line):.0f}% fewer junctions than A* "
              f"with the straight-line heuristic (snow)", worst >= 0 and same == 40 and n_alt < n_line)

    if not full:
        # 5b. accuracy: station-graph distance vs the real shortest road distance (main-road network)
        roads = Graph().load(os.path.join(M.ROADS, "nodes.csv"), os.path.join(M.ROADS, "edges.csv"))
        at = {(round(la, 6), round(lo, 6)): n for n, (_, la, lo) in roads.nodes.items()}
        junction = {r["id"]: at[(round(float(r["junction_lat"]), 6), round(float(r["junction_lon"]), 6))] for r in st}
        worst_lo = worst_hi = 1.0
        for s in sorted({s for s, _ in pairs}):
            rd, _ = M.dijkstra(roads, junction[s])
            for s2, d in pairs:
                if s2 == s:
                    ratio = ucs(g, s, d, "dist")[1] / rd[junction[d]]
                    worst_lo, worst_hi = min(worst_lo, ratio), max(worst_hi, ratio)
        check(f"{tag} station-graph distance / real road distance on {len(pairs)} pairs: "
              f"{worst_lo:.4f} .. {worst_hi:.4f} (must be 1 .. {M.STRETCH})",
              worst_lo >= 1 - 1e-6 and worst_hi <= M.STRETCH + 1e-6)
    else:
        # 5b. exactness: the large station graph's route, timed street by street on the full graph,
        #     is never faster than the full graph's own best route (default and snow)
        gl = Graph().load(os.path.join(HERE, M.LEVELS["large"], "nodes.csv"),
                          os.path.join(HERE, M.LEVELS["large"], "edges.csv"))
        geo_l = {(r["from"], r["to"]): [tuple(map(float, p.split())) for p in r["points"].split(";")]
                 for r in csv.DictReader(open(os.path.join(HERE, M.LEVELS["large"], "geometry.csv"), encoding="utf-8"))}
        at = {(round(la, 6), round(lo, 6)): n for n, (_, la, lo) in g.nodes.items()}
        lm_ids = [i for i in st_ids if i.startswith("U") and i in gl.nodes]
        lp = [(a, b) for a in rng.sample(lm_ids, 12) for b in rng.sample([x for x in lm_ids if x != a], 3)]
        worse, gain, est_err = 0, [], []
        for w, t, cls, exp in settings[:2]:
            gx, glx = cond[(w, t)], (gl if w is None else T.apply_conditions(gl, w, t, by_class=cls))
            for a, b in lp:
                pl, tl, _ = astar(glx, a, b)
                ch = chain_on(g, geo_l, pl, at)
                timed = sum(min(e["time_min"] for e in gx.adj[x] if e["dst"] == y) for x, y in zip(ch, ch[1:]))
                best = astar(gx, a, b)[1]
                worse += best > timed + 1e-6 or ch[0] != a or ch[-1] != b
                gain.append(100 * (timed - best) / timed)
                est_err.append(100 * (tl - timed) / timed)
        dist_ok = all(ucs(g, a, b, "dist")[1] <= ucs(gl, a, b, "dist")[1] + 0.02 for a, b in lp)
        check(f"{tag} exact routing: on {len(lp)} landmark pairs x 2 settings the full graph is never slower than the "
              f"large graph's route (faster by {sum(gain) / len(gain):.1f}% on average, up to {max(gain):.1f}%); "
              f"large-graph time estimates off by {min(est_err):+.1f}%..{max(est_err):+.1f}%; distance never longer",
              worse == 0 and dist_ok)

    # 6. landmarks: same id, name and position as on the small level
    lm = {r["id"]: (r["name"], r["junction_lat"], r["junction_lon"]) for r in st if r["id"].startswith("U")}
    if landmarks_ref is not None:
        same = all(lm.get(i) == v for i, v in landmarks_ref.items())
        extra = [lm[i][0] for i in sorted(set(lm) - set(landmarks_ref))]
        check(f"{tag} the {len(landmarks_ref)} small-level landmarks have the same id, name and position"
              + (f"; extra landmarks that fit on every street: {extra}" if extra else ""), same)

    # 7. geography + the app
    pos = lambda n: g.nodes[byname[n]][1:]
    sq = pos("Sukhbaatar Square")
    geo_ok = [pos("Zaisan Memorial")[0] < sq[0], pos("Narantuul Market")[1] > sq[1],
              pos("Buyant-Ukhaa Airport")[0] < sq[0] and pos("Buyant-Ukhaa Airport")[1] < sq[1],
              pos("Ulaanbaatar Railway Station")[1] < sq[1], pos("Dambadarjaa")[0] > sq[0]]
    _, d_air, _ = ucs(g, "U01", "U33", "dist")
    r = subprocess.run([sys.executable, "app.py", "--data", M.LEVELS[level], "--from", "U01", "--to", "U33", "--compare",
                        "--weather", "snow", "--time", "evening", "peak", "--road-class"],
                       cwd=HERE, capture_output=True, text=True)
    lst = subprocess.run([sys.executable, "app.py", "--data", M.LEVELS[level], "--list"], cwd=HERE,
                         capture_output=True, text=True).stdout.strip().splitlines()
    check(f"{tag} geography right; square -> airport {d_air:.1f} km by road; app.py --data {M.LEVELS[level]} works "
          f"and --list shows the {len(lst)} stations",
          all(geo_ok) and 15 <= d_air <= 25 and r.returncode == 0 and "Same optimal cost: yes" in r.stdout
          and len(lst) == len(st))
    return lm


def run_tests():
    ok = True

    def check(name, cond):
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {name}")
        ok &= bool(cond)

    import make_ub_graph as M
    levels = [lv for lv in M.LEVELS if os.path.exists(os.path.join(HERE, M.LEVELS[lv], "nodes.csv"))]
    ref = None
    for level in levels:
        lm = check_level(level, check, ref)
        ref = ref or lm
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
