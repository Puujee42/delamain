import heapq
import itertools

from graph import Graph


def _cost_index(cost):
    if cost not in ("time", "dist"):
        raise ValueError("cost must be 'time' or 'dist'")
    return 2 if cost == "time" else 1  # index into graph.neighbors() tuple


def _rebuild(parent, goal):
    path = [goal]
    while parent[path[-1]] is not None:
        path.append(parent[path[-1]])
    return path[::-1]


def ucs(g, start, goal, cost="time"):
    """Uniform-Cost Search (Dijkstra)."""
    ci = _cost_index(cost)
    tie = itertools.count()
    pq = [(0.0, next(tie), start)]
    best = {start: 0.0}
    parent = {start: None}
    done, expanded = set(), 0
    while pq:
        c, _, u = heapq.heappop(pq)
        if u in done:
            continue
        done.add(u)
        expanded += 1
        if u == goal:
            return _rebuild(parent, goal), c, expanded
        for nb in g.neighbors(u):
            v, w = nb[0], nb[ci]
            nc = c + w
            if nc < best.get(v, float("inf")):
                best[v] = nc
                parent[v] = u
                heapq.heappush(pq, (nc, next(tie), v))
    return None, float("inf"), expanded


def astar(g, start, goal, cost="time"):
    """A* with admissible straight-line heuristic."""
    ci = _cost_index(cost)

    def h(n):
        if cost == "time":
            return g.heuristic_time_min(n, goal)
        from graph import haversine_km
        _, la, lo = g.nodes[n]
        _, lb, lob = g.nodes[goal]
        return haversine_km(la, lo, lb, lob)  # <= road dist (detour >= 1)

    tie = itertools.count()
    pq = [(h(start), next(tie), 0.0, start)]
    best = {start: 0.0}
    parent = {start: None}
    done, expanded = set(), 0
    while pq:
        _, _, c, u = heapq.heappop(pq)
        if u in done:
            continue
        done.add(u)
        expanded += 1
        if u == goal:
            return _rebuild(parent, goal), c, expanded
        for nb in g.neighbors(u):
            v, w = nb[0], nb[ci]
            nc = c + w
            if nc < best.get(v, float("inf")):
                best[v] = nc
                parent[v] = u
                heapq.heappush(pq, (nc + h(v), next(tie), nc, v))
    return None, float("inf"), expanded


# ------------------------------ tests ------------------------------
def _fmt(g, path):
    return " -> ".join(g.nodes[i][0] for i in path) if path else "no path"


def run_tests():
    g = Graph().load()
    ids = list(g.nodes)
    ok = True

    def check(name, cond):
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {name}")
        ok &= bool(cond)

    # 1. Known route
    p, c, _ = ucs(g, "N01", "N15")
    check("UCS finds Sukhbaatar Sq -> Buyant-Ukhaa", p and p[0] == "N01" and p[-1] == "N15")

    # 2. Start == goal
    p, c, _ = astar(g, "N01", "N01")
    check("A* start==goal gives cost 0", p == ["N01"] and c == 0)

    # 3. UCS and A* agree on optimal cost for ALL pairs, both cost types
    mismatch, a_better, total = 0, 0, 0
    for cost in ("time", "dist"):
        for s in ids:
            for t in ids:
                pu, cu, eu = ucs(g, s, t, cost)
                pa, ca, ea = astar(g, s, t, cost)
                total += 1
                if abs(cu - ca) > 1e-9 or (pu is None) != (pa is None):
                    mismatch += 1
                if ea < eu:
                    a_better += 1
    check(f"UCS == A* optimal cost on all {total} pairs (mismatches: {mismatch})", mismatch == 0)
    print(f"      A* expanded fewer nodes than UCS on {a_better}/{total} pairs")

    # 4. One-way respected: Gandan(N13)->Ard Cinema(N03) exists, reverse edge direct does not
    direct_rev = any(e["dst"] == "N13" for e in g.adj["N03"])
    check("One-way street not usable in reverse", not direct_rev)

    # 5. Blocked road ignored: N11-N04 must not be an edge
    blocked = any(e["dst"] == "N04" for e in g.adj["N11"])
    check("Blocked road (Khan-Uul Link) not used", not blocked)

    # 6. Congestion changes the route/time: compare dist vs time optimum
    _, t_time, _ = ucs(g, "N01", "N08", "time")
    pd, _, _ = ucs(g, "N01", "N08", "dist")
    pt, _, _ = ucs(g, "N01", "N08", "time")
    print(f"      Shortest by distance: {_fmt(g, pd)}")
    print(f"      Fastest by time:      {_fmt(g, pt)} ({t_time:.1f} min)")

    # 7. Unreachable node
    g.nodes["X99"] = ("Island", 0.0, 0.0)
    p, c, _ = ucs(g, "N01", "X99")
    check("Unreachable goal returns no path", p is None and c == float("inf"))

    print("\nALL TESTS PASSED" if ok else "\nSOME TESTS FAILED")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if run_tests() else 1)