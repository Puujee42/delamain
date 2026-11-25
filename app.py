"""app.py - Week XII prototype + Week XIII Bayesian traffic conditions (CLI).

Examples:
  python3 app.py                               # interactive menu
  python3 app.py --from N01 --to N15           # A*, fastest route
  python3 app.py --from N01 --to N08 --algo ucs --cost dist
  python3 app.py --from N01 --to N15 --compare # UCS vs A* side by side
  python3 app.py --list                        # show place ids
  python3 app.py --from N01 --to N15 --compare --weather snow --time morning peak
  python3 app.py --from N01 --to N08 --weather rain            # time unknown
  python3 app.py --from N01 --to N15 --weather snow --time evening peak --road-class
  python3 app.py --from N01 --to N15 --weather snow --time evening peak --road-class --expected-time
  python3 app.py --data data_osm --from N0101 --to N1500 --weather snow --time evening peak --road-class

--weather clear|snow|rain and --time off-peak|morning peak|evening peak feed the
Bayesian network in traffic.py; edges then use the expected congestion.
With neither option the output is exactly the Week XII output.
--road-class (Week XIV) lets narrow central streets react more than bypasses.
--expected-time (Week XV) uses E[travel time] instead of time at E[congestion];
--k-file FILE (Week XV) uses road-class sensitivities fitted by calibrate.py.
"""
import argparse
import json
import re
import sys
import time

from graph import Graph
from search import ucs, astar
from traffic import (apply_conditions, congestion_dist, expected_congestion,
                     normalize, WEATHER, TIME, LEVEL)

ALGOS = {"ucs": ucs, "astar": astar}


def names(g, path):
    return " -> ".join(g.nodes[i][0] for i in path)


SHOW_ROADS = False  # --roads


def road_names(g, path):
    """Named roads along a path, consecutive duplicates removed (unnamed OSM
    pieces like 'tertiary 123' are skipped)."""
    out = []
    for a, b in zip(path, path[1:]):
        r = next(e["road"] for e in g.adj[a] if e["dst"] == b)
        if re.match(r"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential)(_link)? \d+$", r):
            continue
        if not out or out[-1] != r:
            out.append(r)
    return out


def run_one(g, algo, s, t, cost):
    t0 = time.perf_counter()
    path, c, exp = ALGOS[algo](g, s, t, cost)
    ms = (time.perf_counter() - t0) * 1000
    return path, c, exp, ms


def show(g, algo, s, t, cost):
    path, c, exp, ms = run_one(g, algo, s, t, cost)
    unit = "min" if cost == "time" else "km"
    print(f"[{algo.upper()}] {g.nodes[s][0]} -> {g.nodes[t][0]} (optimize: {cost})")
    if path is None:
        print("  No route found (closed road or one-way street).")
        return
    print(f"  Route : {names(g, path)}")
    if SHOW_ROADS:
        print(f"  Roads : {' -> '.join(road_names(g, path))} ({len(path)} stops)")
    print(f"  Cost  : {c:.2f} {unit} | expanded {exp} nodes | {ms:.2f} ms")


def compare(g, s, t, cost):
    print(f"--- Compare on {g.nodes[s][0]} -> {g.nodes[t][0]} ({cost}) ---")
    res = {}
    for a in ("ucs", "astar"):
        res[a] = run_one(g, a, s, t, cost)
        show(g, a, s, t, cost)
    u, a_ = res["ucs"], res["astar"]
    same = (u[0] is None and a_[0] is None) or abs(u[1] - a_[1]) < 1e-9
    print(f"  Same optimal cost: {'yes' if same else 'NO'} | "
          f"A* expanded {u[2] - a_[2]} fewer nodes")


def list_places(g):
    for i, (n, la, lo) in g.nodes.items():
        print(f"  {i}  {n}")


def pick(g, prompt):
    list_places(g)
    while True:
        v = input(prompt).strip().upper()
        if v in g.nodes:
            return v
        print("  Unknown id, try again (e.g. N01).")


def interactive(g):
    print("=== UBT route finder ===")
    while True:
        s = pick(g, "From id: ")
        t = pick(g, "To id  : ")
        cost = input("Optimize [time/dist] (time): ").strip() or "time"
        compare(g, s, t, cost if cost in ("time", "dist") else "time")
        if input("Another? [y/N]: ").strip().lower() != "y":
            break


def main():
    ap = argparse.ArgumentParser(description="UBT route search prototype")
    ap.add_argument("--from", dest="s")
    ap.add_argument("--to", dest="t")
    ap.add_argument("--algo", choices=ALGOS, default="astar")
    ap.add_argument("--cost", choices=["time", "dist"], default="time")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--data", default=".", help="folder with nodes.csv + edges.csv (default: current)")
    ap.add_argument("--weather", help="Bayesian network input: " + " | ".join(WEATHER))
    ap.add_argument("--time", nargs="+", metavar="TIME",
                    help="Bayesian network input: off-peak | morning peak | evening peak")
    ap.add_argument("--road-class", action="store_true",
                    help="road-class sensitivity: local x1.5, main x1.0, arterial x0.5 (with --weather/--time)")
    ap.add_argument("--expected-time", action="store_true",
                    help="edge weight = expected travel time E[t] instead of t(E[congestion]) (with --weather/--time)")
    ap.add_argument("--k-file", help="JSON from calibrate.py --save; implies --road-class with the fitted k")
    ap.add_argument("--roads", action="store_true", help="also print the named roads along the route")
    a = ap.parse_args()
    global SHOW_ROADS
    SHOW_ROADS = a.roads
    try:
        weather = normalize(a.weather, WEATHER)
        tod = normalize(" ".join(a.time), TIME) if a.time else None
    except ValueError as err:
        ap.error(str(err))
    kmap = None
    if a.k_file:
        try:
            kmap = {c: float(v) for c, v in json.load(open(a.k_file, encoding="utf-8"))["k"].items()}
        except (OSError, ValueError, KeyError) as err:
            ap.error(f"--k-file: {err}")
        if set(kmap) != {"local", "main", "arterial"}:
            ap.error("--k-file: k must have local, main, arterial")
    g = Graph().load(f"{a.data}/nodes.csv", f"{a.data}/edges.csv")
    if weather or tod:
        g = apply_conditions(g, weather, tod, by_class=a.road_class or bool(kmap), k=kmap,
                             expected="time" if a.expected_time else "congestion")
        p = congestion_dist(weather, tod)
        print(f"[Bayes] weather={weather or 'any'}, time={tod or 'any'} -> "
              f"P(congestion low/medium/high) = {' / '.join(f'{p[l]:.2f}' for l in LEVEL)}, "
              f"expected level {expected_congestion(weather, tod):.2f}"
              + (" | road-class model" if a.road_class and not kmap else "")
              + (f" | fitted k {kmap['local']}/{kmap['main']}/{kmap['arterial']}" if kmap else "")
              + (" | E[travel time]" if a.expected_time else ""))
    elif a.road_class or a.expected_time or a.k_file:
        ap.error("--road-class / --expected-time / --k-file need --weather and/or --time")
    if a.list:
        return list_places(g)
    if not (a.s and a.t):
        return interactive(g)
    for x in (a.s, a.t):
        if x not in g.nodes:
            sys.exit(f"Unknown node {x}. Use --list.")
    compare(g, a.s, a.t, a.cost) if a.compare else show(g, a.algo, a.s, a.t, a.cost)


if __name__ == "__main__":
    main()
