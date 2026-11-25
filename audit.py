"""audit.py - dataset quality audit for the road graph (nodes.csv + edges.csv).

  python3 audit.py                 # audit ./nodes.csv + ./edges.csv
  python3 audit.py data_osm        # audit another folder

Prints a scorecard (PASS / WARN / FAIL) and writes audit_report.md.
"""
import csv
import math
import statistics as st
import sys
from collections import defaultdict

from graph import haversine_km

UB_BBOX = (47.75, 48.05, 106.65, 107.25)  # lat_min, lat_max, lon_min, lon_max (Ulaanbaatar area)


def scc(nodes, adj):
    """Tarjan strongly connected components (iterative)."""
    index, low, on, stack, out, idx = {}, {}, set(), [], [], [0]
    for root in nodes:
        if root in index:
            continue
        work = [(root, iter(adj[root]))]
        index[root] = low[root] = idx[0]; idx[0] += 1; stack.append(root); on.add(root)
        while work:
            v, it = work[-1]
            adv = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = idx[0]; idx[0] += 1; stack.append(w); on.add(w)
                    work.append((w, iter(adj[w]))); adv = True; break
                elif w in on:
                    low[v] = min(low[v], index[w])
            if adv:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop(); on.discard(w); comp.append(w)
                    if w == v:
                        break
                out.append(comp)
    return out


def audit(folder="."):
    nodes = {r["id"]: r for r in csv.DictReader(open(f"{folder}/nodes.csv", encoding="utf-8"))}
    edges = list(csv.DictReader(open(f"{folder}/edges.csv", encoding="utf-8")))
    cols = set(edges[0])
    checks = []

    def add(level, name, detail):
        checks.append((level, name, detail))

    n, m = len(nodes), len(edges)
    add("INFO", "Size", f"{n} nodes, {m} road segments")

    # structural
    unknown = [e for e in edges if e["from"] not in nodes or e["to"] not in nodes]
    add("PASS" if not unknown else "FAIL", "Edges reference existing nodes", f"{len(unknown)} bad")
    loops = [e for e in edges if e["from"] == e["to"]]
    add("PASS" if not loops else "FAIL", "No self-loops", f"{len(loops)} found")
    seen, dup = set(), 0
    for e in edges:
        k = (e["from"], e["to"], e["road"])
        dup += k in seen; seen.add(k)
    add("PASS" if not dup else "WARN", "No duplicate segments", f"{dup} duplicates")

    # geometry
    bad_bbox = [i for i, r in nodes.items() if not (UB_BBOX[0] <= float(r["lat"]) <= UB_BBOX[1] and UB_BBOX[2] <= float(r["lon"]) <= UB_BBOX[3])]
    add("PASS" if not bad_bbox else "FAIL", "All nodes inside Ulaanbaatar bounding box", f"{len(bad_bbox)} outside")
    if "length_km" in cols:
        ratios = []
        for e in edges:
            a, b = nodes[e["from"]], nodes[e["to"]]
            h = haversine_km(float(a["lat"]), float(a["lon"]), float(b["lat"]), float(b["lon"]))
            if h > 0.005:
                ratios.append(float(e["length_km"]) / h)
        low = sum(r < 0.98 for r in ratios)
        add("PASS" if low == 0 else "FAIL", "Road length >= straight-line distance", f"{low} violations (median ratio {st.median(ratios):.2f})")
        add("PASS", "Lengths measured from map geometry", "length_km column present")
    else:
        add("WARN", "Lengths are estimated (straight line x 1.3), not measured", "no length_km column")

    # attributes
    sp = [float(e["speed_limit_kmh"]) for e in edges]
    odd = [s for s in sp if s < 10 or s > 120]
    add("PASS" if not odd else "FAIL", "Speed limits in 10-120 km/h", f"{len(odd)} outliers, range {min(sp):.0f}-{max(sp):.0f}")
    cg = [float(e["base_congestion"]) for e in edges]
    add("PASS" if all(0 <= c <= 1 for c in cg) else "FAIL", "Congestion within 0-1", f"mean {st.mean(cg):.2f}")
    src = {e.get("congestion_source", "") for e in edges}
    real = "measured" in src
    add("PASS" if real else "WARN", "Congestion comes from real measurements",
        "measured" if real else "synthetic / assumed (no real traffic data)")
    add("PASS" if "highway" in cols else "WARN", "Road class (highway) recorded", "yes" if "highway" in cols else "missing: cannot vary congestion by road type")

    # connectivity
    adj = defaultdict(list)
    und = defaultdict(set)
    for e in edges:
        if e["blocked"] == "1":
            continue
        adj[e["from"]].append(e["to"])
        und[e["from"]].add(e["to"]); und[e["to"]].add(e["from"])
        if e["oneway"] == "0":
            adj[e["to"]].append(e["from"])
    for i in nodes:
        adj.setdefault(i, []); und.setdefault(i, set())
    comps = sorted(scc(list(nodes), adj), key=len, reverse=True)
    big = len(comps[0])
    add("PASS" if big == n else "WARN", "Graph strongly connected (every place can reach every place)",
        f"largest component {big}/{n} nodes ({100*big/n:.0f}%), {len(comps)} components")
    seenc, comp_und = set(), 0
    for s in nodes:
        if s in seenc:
            continue
        comp_und += 1
        stack = [s]; seenc.add(s)
        while stack:
            u = stack.pop()
            for w in und[u]:
                if w not in seenc:
                    seenc.add(w); stack.append(w)
    undirected_edges = len({frozenset((e["from"], e["to"])) for e in edges})
    cyc = undirected_edges - n + comp_und
    add("PASS" if cyc >= 0.3 * n else "WARN", "Alternative routes exist (independent cycles >= 30% of nodes)",
        f"{cyc} cycles for {n} nodes ({cyc/n:.2f} per node)")
    deg = [len(und[i]) for i in nodes]
    dead = sum(d == 1 for d in deg)
    add("PASS" if dead <= 0.15 * n else "WARN", "Few dead-end nodes (<= 15%)", f"{dead} dead ends ({100*dead/n:.0f}%)")
    ow = sum(e["oneway"] == "1" for e in edges)
    add("INFO", "One-way segments", f"{ow}/{m} ({100*ow/m:.0f}%)")
    blocked = sum(e["blocked"] == "1" for e in edges)
    add("INFO", "Closed segments", f"{blocked}")
    return checks


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "."
    checks = audit(folder)
    score = [c for c in checks if c[0] in ("PASS", "WARN", "FAIL")]
    p = sum(c[0] == "PASS" for c in score)
    lines = [f"# Dataset audit: {folder}", "", f"Score: {p}/{len(score)} checks passed", "", "| Result | Check | Detail |", "| --- | --- | --- |"]
    print(f"=== Dataset audit: {folder} ===")
    for lvl, name, detail in checks:
        print(f"[{lvl:4}] {name}: {detail}")
        lines.append(f"| {lvl} | {name} | {detail} |")
    print(f"\nScore: {p}/{len(score)} checks passed")
    open("audit_report.md", "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
