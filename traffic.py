"""traffic.py - Week XIII: Bayesian network for congestion + edge-weight update.

Network (3 discrete variables, no new dependencies, exact inference):

    Weather (clear / snow / rain) ─────┐
                                       ├──> Congestion (low / medium / high)
    Time    (off_peak / morning_peak / ┘
             evening_peak)

    P(W, T, C) = P(W) * P(T) * P(C | W, T)

How it reaches the road graph
-----------------------------
Congestion is a CITY-WIDE level. Each road keeps its own character from
edges.csv (base_congestion = the road under a "medium" city level) and the
level shifts it up or down:

    c_e(level)          = clip(base_e + SHIFT[level], 0, 0.95)
    E[c_e | w, t]       = sum_level P(level | w, t) * c_e(level)
    time_e(w, t) [min]  = dist_e / (speed_e * (1 - 0.7 * E[c_e | w, t])) * 60

The edge weight therefore uses the probabilistic (expected) congestion.
Why A* stays admissible / UCS + A* stay optimal: E[c_e] is clipped to
[0, 0.95] so the effective speed is speed_e*(1-0.7c) <= speed_e <= 70 km/h,
and dist_e >= straight-line distance. Every edge therefore costs at least
straight_line(u, v) / 70 km/h, which makes h = straight_line(n, goal) / 70
consistent (hence admissible). All weights stay positive (>= 0.335*speed).

ALL NUMBERS BELOW ARE ASSUMPTIONS (no measured traffic data yet). Where they
come from is written next to each table. Replace with measured counts later.

Usage:
    g = Graph().load()
    g2 = apply_conditions(g, weather="snow", time="morning_peak")
    astar(g2, "N01", "N15")         # routes now use the updated weights

    python3 traffic.py              # tests (PASS/FAIL, exit code)
    python3 traffic.py --demo       # tables + routes under several conditions
"""
import copy
import itertools

from graph import Graph

# ----------------------------- model (CPDs) -----------------------------
WEATHER = ["clear", "snow", "rain"]
TIME = ["off_peak", "morning_peak", "evening_peak"]
LEVEL = ["low", "medium", "high"]

# P(Weather). Source: Ulaanbaatar is very dry (~250 sunny days/yr, ~250 mm
# precipitation/yr). We assume ~30% of days have precipitation, split evenly
# between snow (Oct-Apr) and rain (Jun-Aug). Synthetic, rounded.
P_WEATHER = {"clear": 0.70, "snow": 0.15, "rain": 0.15}

# P(Time of day) = share of the 24 h day (a random moment, not a random trip):
#   morning peak 07:30-10:00 = 2.5 h -> 2.5/24 ~ 0.10
#   evening peak 17:00-20:30 = 3.5 h -> 3.5/24 ~ 0.15
#   off-peak     the other   18 h    ->  18/24 = 0.75
P_TIME = {"off_peak": 0.75, "morning_peak": 0.10, "evening_peak": 0.15}

# P(Congestion = low, medium, high | Weather, Time).  Expert-style guesses
# that follow three qualitative rules (no measured data):
#   1. peak > off-peak, and the UB evening peak is worse than the morning one
#      (school + work + shopping traffic overlaps in the evening);
#   2. snow > rain > clear (ice, few snow ploughs, slower driving);
#   3. every row is a probability distribution (sums to 1, checked in tests).
CPD_CONG = {
    #                         low   medium high
    ("clear", "off_peak"):     [0.60, 0.30, 0.10],
    ("clear", "morning_peak"): [0.15, 0.45, 0.40],
    ("clear", "evening_peak"): [0.10, 0.40, 0.50],
    ("snow", "off_peak"):      [0.30, 0.45, 0.25],
    ("snow", "morning_peak"):  [0.05, 0.30, 0.65],
    ("snow", "evening_peak"):  [0.03, 0.22, 0.75],
    ("rain", "off_peak"):      [0.45, 0.38, 0.17],
    ("rain", "morning_peak"):  [0.10, 0.40, 0.50],
    ("rain", "evening_peak"):  [0.06, 0.34, 0.60],
}

# City-level congestion as a number 0..1 (used only for the one-line summary
# "expected congestion" in app.py / experiments): middle of each band.
LEVEL_VALUE = {"low": 0.15, "medium": 0.50, "high": 0.85}

# How a city-wide level moves one road's congestion away from its base value.
# base_congestion in edges.csv is read as the road on a "medium" day.
SHIFT = {"low": -0.25, "medium": 0.0, "high": +0.25}
C_MIN, C_MAX = 0.0, 0.95  # keeps 1 - 0.7c in [0.335, 1] -> speed <= limit

# Week XIV (optional, apply_conditions(..., by_class=True) / app.py --road-class):
# roads do not react equally to a city-wide jam. The shift is multiplied by a
# sensitivity k per road class:  c_e(level) = clip(base_e + k_class * SHIFT[level]).
# edges.csv has no road-class column, so the class is read from the speed limit.
# Numbers are ASSUMPTIONS (no data): narrow 40 km/h central streets have many
# lights, crossings and parked cars, so peak demand fills them first (x1.5);
# 60-70 km/h bypass / outer roads have spare capacity (x0.5); 50 km/h = x1.0.
# Clipping to [0, 0.95] is unchanged, so A* stays admissible.
ROAD_CLASS_K = {"local": 1.5, "main": 1.0, "arterial": 0.5}


# Week XV: OSM graphs carry the real road class (edges.csv column `highway`).
# Assumed mapping: motorway / trunk = arterial (grade-separated, spare capacity),
# primary / secondary = main, tertiary and smaller = local.
HIGHWAY_CLASS = {"motorway": "arterial", "trunk": "arterial", "primary": "main", "secondary": "main",
                 "tertiary": "local", "unclassified": "local", "residential": "local", "living_street": "local"}


def road_class(speed_kmh, highway=None):
    """'local' / 'main' / 'arterial'. Uses the OSM highway tag when there is one,
    else the speed limit: <= 40 km/h local, <= 50 km/h main, faster arterial."""
    h = (highway or "").replace("_link", "")
    if h in HIGHWAY_CLASS:
        return HIGHWAY_CLASS[h]
    if speed_kmh <= 40:
        return "local"
    return "main" if speed_kmh <= 50 else "arterial"


# ----------------------------- input names -----------------------------
def normalize(value, domain):
    """'morning peak', 'Morning-Peak', 'morning_peak' -> 'morning_peak'."""
    if value is None:
        return None
    v = "_".join(str(value).strip().lower().replace("-", " ").replace("_", " ").split())
    if v == "offpeak":
        v = "off_peak"
    if v not in domain:
        raise ValueError(f"{value!r} is not one of {', '.join(domain)}")
    return v


# ----------------------------- inference -----------------------------
def joint(w, t, c):
    """P(W=w, T=t, C=c) = P(w) P(t) P(c | w, t)."""
    return P_WEATHER[w] * P_TIME[t] * CPD_CONG[(w, t)][LEVEL.index(c)]


def posterior(query, evidence=None):
    """Exact inference by enumeration of the 3*3*3 = 27 joint entries.
    query in {'weather', 'time', 'congestion'}; evidence: dict of observed values."""
    evidence = evidence or {}
    domains = {"weather": WEATHER, "time": TIME, "congestion": LEVEL}
    scores = {v: 0.0 for v in domains[query]}
    for w, t, c in itertools.product(WEATHER, TIME, LEVEL):
        a = {"weather": w, "time": t, "congestion": c}
        if any(a[k] != v for k, v in evidence.items()):
            continue
        scores[a[query]] += joint(w, t, c)
    z = sum(scores.values())
    if z == 0:
        raise ValueError("Evidence has probability 0")
    return {k: v / z for k, v in scores.items()}


def _evidence(weather=None, time=None):
    ev = {}
    if weather:
        ev["weather"] = normalize(weather, WEATHER)
    if time:
        ev["time"] = normalize(time, TIME)
    return ev


def congestion_dist(weather=None, time=None):
    """P(congestion | weather, time) as {'low': p, 'medium': p, 'high': p}.
    A missing input is summed out with its prior."""
    return posterior("congestion", _evidence(weather, time))


def expected_congestion(weather=None, time=None):
    """City-level E[congestion value 0..1] given the (optional) weather / time."""
    p = congestion_dist(weather, time)
    return sum(p[l] * LEVEL_VALUE[l] for l in LEVEL)


def edge_congestion(base, level, k=1.0):
    """Congestion of one road (base value from edges.csv) on a city `level` day;
    k = road-class sensitivity (1.0 = Week XIII uniform model)."""
    return min(C_MAX, max(C_MIN, base + k * SHIFT[level]))


def expected_edge_congestion(base, weather=None, time=None, dist=None, k=1.0):
    """E[c_e | weather, time] = sum_l P(l | w, t) * clip(base + k * SHIFT[l])."""
    p = dist or congestion_dist(weather, time)
    return sum(p[l] * edge_congestion(base, l, k) for l in LEVEL)


# ----------------------------- graph update -----------------------------
def expected_edge_time(dist_km, speed_kmh, base, dist, k=1.0, signals=0):
    """Week XV: E[t_e] = sum_l P(l | w, t) * time(c_e(l)) - the expected travel
    time, which is >= time(E[c_e]) because time grows faster than linearly
    in congestion (Jensen). Every term is >= straight line / top speed, so
    A* stays admissible."""
    return sum(dist[l] * (Graph.travel_time_min(dist_km, speed_kmh, edge_congestion(base, l, k))
                          + Graph.signal_delay_min(signals, edge_congestion(base, l, k))) for l in LEVEL)


def apply_conditions(g, weather=None, time=None, by_class=False, k=None, expected="congestion"):
    """Return a COPY of g whose edges use the given weather / time (either may
    be None = unknown, summed out). The original graph is not modified.

    by_class=True   scale each road's shift by its class sensitivity (Week XIV);
    k               optional {'local','main','arterial'} -> sensitivity, overrides
                    ROAD_CLASS_K (used by calibrate.py);
    expected        'congestion' (Week XIII: time at E[c]) or 'time' (Week XV: E[t]).
    Each edge keeps 'base_congestion' (from edges.csv); 'congestion' = E[c] and
    'time_min' are replaced."""
    if expected not in ("congestion", "time"):
        raise ValueError("expected must be 'congestion' or 'time'")
    kmap = k or ROAD_CLASS_K
    p = congestion_dist(weather, time)
    g2 = copy.deepcopy(g)
    for e in g2.edges:  # g.edges and g.adj share the same dicts (deepcopy keeps that)
        base = e.get("base_congestion", e["congestion"])
        ke = kmap[road_class(e["speed_kmh"], e.get("highway"))] if (by_class or k) else 1.0
        c = expected_edge_congestion(base, dist=p, k=ke)
        e["base_congestion"] = base
        e["congestion"] = round(c, 4)
        sig = e.get("signals", 0)  # traffic lights: wait grows with congestion (graph.py)
        t = (expected_edge_time(e["distance_km"], e["speed_kmh"], base, p, ke, sig) if expected == "time"
             else Graph.travel_time_min(e["distance_km"], e["speed_kmh"], c) + Graph.signal_delay_min(sig, c))
        e["time_min"] = g2.round_time(t)
    return g2


def observe_edge(g, src, dst, observed_level, strength=0.5):
    """Online update: a sensor reports `observed_level` on one road. Move that
    road's congestion toward the level's value (strength 0..1). Returns a copy."""
    g2 = copy.deepcopy(g)
    target = LEVEL_VALUE[observed_level]
    for e in g2.edges:
        if {e["src"], e["dst"]} == {src, dst}:
            c = (1 - strength) * e["congestion"] + strength * target
            e["congestion"] = round(c, 3)
            e["time_min"] = g2.round_time(Graph.travel_time_min(e["distance_km"], e["speed_kmh"], c)
                                          + Graph.signal_delay_min(e.get("signals", 0), c))
    return g2


# ----------------------------- tests -----------------------------
def _edge(g, a, b):
    return next(e for e in g.edges if e["src"] == a and e["dst"] == b)


def run_tests():
    from search import ucs, astar

    ok = True

    def check(name, cond):
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {name}")
        ok &= bool(cond)

    # 1. every CPD row sums to 1, priors sum to 1, all rows present
    check(f"All {len(CPD_CONG)} CPD rows of P(C | W, T) sum to 1",
          len(CPD_CONG) == len(WEATHER) * len(TIME)
          and all(abs(sum(r) - 1) < 1e-9 and min(r) >= 0 for r in CPD_CONG.values()))
    check("Priors P(W) and P(T) sum to 1",
          abs(sum(P_WEATHER.values()) - 1) < 1e-9 and abs(sum(P_TIME.values()) - 1) < 1e-9)
    check("Joint P(W, T, C) sums to 1 over all 27 entries",
          abs(sum(joint(w, t, c) for w in WEATHER for t in TIME for c in LEVEL) - 1) < 1e-12)

    # 2. Hand case A - full evidence returns the CPD row.
    #    P(C | snow, morning_peak) = [0.05, 0.30, 0.65]   (table row)
    #    E[level] = 0.05*0.15 + 0.30*0.50 + 0.65*0.85 = 0.0075 + 0.15 + 0.5525 = 0.71
    p = congestion_dist("snow", "morning peak")
    check("Hand A: P(C | snow, morning peak) = [0.05, 0.30, 0.65], E = 0.71",
          all(abs(p[l] - v) < 1e-12 for l, v in zip(LEVEL, [0.05, 0.30, 0.65]))
          and abs(expected_congestion("snow", "morning_peak") - 0.71) < 1e-12)

    # 3. Hand case B - time unknown, summed out with its prior.
    #    P(high | rain) = 0.75*0.17 + 0.10*0.50 + 0.15*0.60
    #                   = 0.1275 + 0.05 + 0.09 = 0.2675
    check("Hand B: P(high | rain) = 0.2675 (time summed out)",
          abs(congestion_dist("rain")["high"] - 0.2675) < 1e-12)

    # 4. Hand case C - Bayes rule, reasoning backwards from congestion to weather.
    #    P(high | clear) = 0.75*0.10 + 0.10*0.40 + 0.15*0.50 = 0.075+0.04+0.075   = 0.19
    #    P(high | snow)  = 0.75*0.25 + 0.10*0.65 + 0.15*0.75 = 0.1875+0.065+0.1125 = 0.365
    #    P(high | rain)  = 0.2675                                           (case B)
    #    P(high) = 0.70*0.19 + 0.15*0.365 + 0.15*0.2675
    #            = 0.133 + 0.05475 + 0.040125 = 0.227875
    #    P(snow | high) = 0.05475 / 0.227875 = 0.240263...
    check("Hand C: P(snow | high) = 0.05475 / 0.227875 = 0.2403 (Bayes rule)",
          abs(posterior("weather", {"congestion": "high"})["snow"] - 0.05475 / 0.227875) < 1e-12)

    # 5. Hand case D - one road. Peace Avenue N01->N02: base 0.70, 40 km/h, 1.463 km.
    #    snow + morning_peak:  levels low/med/high -> c = 0.45 / 0.70 / 0.95
    #    E[c] = 0.05*0.45 + 0.30*0.70 + 0.65*0.95 = 0.0225 + 0.21 + 0.6175 = 0.85
    #    time = 1.463 / (40 * (1 - 0.7*0.85)) * 60 = 1.463 / 16.2 * 60 = 5.418 -> 5.42 min
    #    (default graph: 1.463 / (40*0.51) * 60 = 4.30 min)
    g = Graph().load()
    gs = apply_conditions(g, "snow", "morning_peak")
    e = _edge(gs, "N01", "N02")
    check(f"Hand D: N01->N02 snow+morning E[c] = 0.85, time 4.30 -> 5.42 min (got {e['congestion']}, {e['time_min']})",
          abs(e["congestion"] - 0.85) < 1e-9 and e["time_min"] == 5.42 and _edge(g, "N01", "N02")["time_min"] == 4.30)

    # 6. Hand case E - clipping at 0. Airport Road N10->N15: base 0.20, 70 km/h, 6.444 km.
    #    clear + off_peak: c = clip(-0.05)=0.00 / 0.20 / 0.45
    #    E[c] = 0.60*0.00 + 0.30*0.20 + 0.10*0.45 = 0.06 + 0.045 = 0.105
    #    time = 6.444 / (70 * (1 - 0.0735)) * 60 = 6.444 / 64.855 * 60 = 5.96 min
    e = _edge(apply_conditions(g, "clear", "off_peak"), "N10", "N15")
    check(f"Hand E: N10->N15 clear+off-peak E[c] = 0.105, time 5.96 min (got {e['congestion']}, {e['time_min']})",
          abs(e["congestion"] - 0.105) < 1e-9 and e["time_min"] == 5.96)

    # 7. ordering of the model + original graph untouched
    check("E[congestion]: snow+evening > rain+evening > clear+evening > clear+off-peak",
          expected_congestion("snow", "evening_peak") > expected_congestion("rain", "evening_peak")
          > expected_congestion("clear", "evening_peak") > expected_congestion("clear", "off_peak"))
    before = [(x["congestion"], x["time_min"]) for x in g.edges]
    apply_conditions(g, "snow", "evening_peak")
    check("Original graph unchanged by apply_conditions",
          before == [(x["congestion"], x["time_min"]) for x in g.edges])

    # 8. Admissibility / consistency: under every condition each edge costs at least
    #    straight_line(u, v) / 70 km/h, the same bound the A* heuristic uses.
    conds = [(w, t) for w in WEATHER for t in TIME] + [("snow", None), (None, "evening_peak"), (None, None)]
    worst = min(e["time_min"] - gc.heuristic_time_min(e["src"], e["dst"])
                for w, t in conds for gc in [apply_conditions(g, w, t)] for e in gc.edges)
    check(f"Heuristic consistent on every edge, all {len(conds)} conditions (min slack {worst:.2f} min)",
          worst >= 0 and all(e["speed_kmh"] <= 70 for e in g.edges))

    # 9. 210-pair optimality: UCS == A* on every ordered pair i != j, both cost
    #    types, under all 9 weather/time combinations + 3 partial-evidence cases.
    ids = list(g.nodes)
    pairs = [(s, t) for s in ids for t in ids if s != t]
    for w, t in conds:
        gc = apply_conditions(g, w, t)
        bad = 0
        for cost in ("time", "dist"):
            for s, d in pairs:
                pu, cu, _ = ucs(gc, s, d, cost)
                pa, ca, _ = astar(gc, s, d, cost)
                if (pu is None) != (pa is None) or abs(cu - ca) > 1e-9:
                    bad += 1
        check(f"UCS == A* on all {len(pairs)} pairs x time/dist, {w or 'any'}+{t or 'any'} (mismatches: {bad})",
              len(pairs) == 210 and bad == 0)

    # 10. sensor observation raises a road's congestion
    g3 = observe_edge(g, "N01", "N07", "high", strength=0.6)
    c0, c1 = _edge(g, "N01", "N07")["congestion"], _edge(g3, "N01", "N07")["congestion"]
    check(f"Observation updates road ({c0} -> {c1})", c1 > c0)

    # 11. input names
    check("normalize: 'morning peak' / 'Off-Peak' accepted",
          normalize("morning peak", TIME) == "morning_peak" and normalize("Off-Peak", TIME) == "off_peak")

    print("\nALL TESTS PASSED" if ok else "\nSOME TESTS FAILED")
    return ok


def demo():
    from search import astar
    g = Graph().load()
    names = lambda p: " -> ".join(g.nodes[i][0] for i in p)
    print("P(congestion | weather, time) and expected city level:")
    print(f"{'weather':8}{'time':14}{'low':>6}{'med':>6}{'high':>6}{'E[c]':>7}")
    for w in WEATHER:
        for t in TIME:
            p = congestion_dist(w, t)
            print(f"{w:8}{t:14}{p['low']:6.2f}{p['medium']:6.2f}{p['high']:6.2f}{expected_congestion(w, t):7.2f}")
    print("\nP(time | congestion = high):",
          {k: round(v, 3) for k, v in posterior("time", {"congestion": "high"}).items()})
    print("P(weather | congestion = high):",
          {k: round(v, 3) for k, v in posterior("weather", {"congestion": "high"}).items()})
    print("\nExpected congestion per edge (first 5 roads):")
    for e in g.edges[:5]:
        vals = " ".join(f"{expected_edge_congestion(e['congestion'], w, t):.3f}"
                        for w, t in [("clear", "off_peak"), ("rain", "morning_peak"), ("snow", "morning_peak")])
        print(f"  {e['src']}->{e['dst']} base {e['congestion']:.2f} | clear+off {vals.split()[0]} "
              f"rain+morning {vals.split()[1]} snow+morning {vals.split()[2]}")
    print("\nRoutes (A*, time):")
    for s, t in [("N01", "N15"), ("N01", "N08")]:
        for w, tm in [(None, None), ("clear", "off_peak"), ("snow", "morning_peak")]:
            gg = g if w is None else apply_conditions(g, w, tm)
            p, c, _ = astar(gg, s, t)
            print(f"  {(w or 'default'):7}+{(tm or '-'):13} {g.nodes[s][0]} -> {g.nodes[t][0]}: {c:5.2f} min | {names(p)}")


if __name__ == "__main__":
    import sys
    if "--demo" in sys.argv:
        demo()
    else:
        sys.exit(0 if run_tests() else 1)
