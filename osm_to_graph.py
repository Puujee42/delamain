"""osm_to_graph.py - convert an OpenStreetMap XML export into nodes.csv / edges.csv.

Standard library only (+ defusedxml if installed, for safe XML parsing).

How to get the OSM file (do this on your own computer, the workspace is offline):
  A) openstreetmap.org -> Export -> select Ulaanbaatar -> Export (.osm), or
  B) https://overpass-turbo.eu  run this query, then Export -> "raw OSM data":
       [out:xml][timeout:90];
       ( way["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential)(_link)?$"]
         (47.85,106.75,47.98,107.05); );
       (._;>;); out body;

Run:
  python3 osm_to_graph.py map.osm --out data_osm --min-class tertiary
  python3 audit.py data_osm
  python3 app.py --data data_osm --list

What comes from the map: geometry, real road length, road names, road class, one-way,
maxspeed (when tagged). What is still ASSUMED: speeds for untagged roads (class default)
and congestion (class default). Columns speed_source / congestion_source say which.
"""
import argparse
import csv
import math
import os
import re
from collections import defaultdict

try:
    from defusedxml import ElementTree as ET
except ImportError:  # fine for your own export; install defusedxml for untrusted files
    import xml.etree.ElementTree as ET

from audit import scc

CLASS_ORDER = ["motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential"]
DEFAULT_SPEED = {"motorway": 80, "trunk": 70, "primary": 60, "secondary": 50, "tertiary": 40,
                 "unclassified": 40, "residential": 30}
# ASSUMED typical congestion (0-1) by class; replace with measured values when you have them.
DEFAULT_CONG = {"motorway": 0.35, "trunk": 0.45, "primary": 0.55, "secondary": 0.45, "tertiary": 0.35,
                "unclassified": 0.25, "residential": 0.20}


def hav(a, b):
    r = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dl = math.radians(b[1] - a[1])
    x = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(x))


def parse_speed(v):
    if not v:
        return None
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(mph)?\s*$", v)
    if not m:
        return None
    s = float(m.group(1)) * (1.609 if m.group(2) else 1)
    return round(s) if 5 <= s <= 140 else None


def base_class(h):
    h = h.replace("_link", "")
    return h if h in CLASS_ORDER else None


def read_osm(path, min_class):
    allowed = set(CLASS_ORDER[: CLASS_ORDER.index(min_class) + 1])
    pts, ways = {}, []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "node":
            pts[el.get("id")] = (float(el.get("lat")), float(el.get("lon")))
        elif el.tag == "way":
            tags = {t.get("k"): t.get("v") for t in el.findall("tag")}
            cls = base_class(tags.get("highway", ""))
            if cls in allowed and tags.get("access") not in ("no", "private"):
                refs = [n.get("ref") for n in el.findall("nd")]
                if len(refs) >= 2 and all(r in pts for r in refs):
                    ways.append((el.get("id"), cls, tags, refs))
            el.clear()
    return pts, ways


def build(pts, ways):
    use = defaultdict(int)
    for _, _, _, refs in ways:
        for r in set(refs):
            use[r] += 1
    keep = {r for _, _, _, refs in ways for r in (refs[0], refs[-1])}
    keep |= {r for r, c in use.items() if c >= 2}
    seg = {}  # (u, v) directed -> best edge dict
    for wid, cls, tags, refs in ways:
        name = tags.get("name:en") or tags.get("name") or ""
        speed = parse_speed(tags.get("maxspeed"))
        sp_src = "tag" if speed else "class_default"
        speed = speed or DEFAULT_SPEED[cls]
        ow = tags.get("oneway", "")
        rev = ow == "-1"
        one = ow in ("yes", "true", "1", "-1") or tags.get("junction") == "roundabout" or (cls == "motorway" and ow != "no")
        lanes = tags.get("lanes", "")
        cur, length = refs[0], 0.0
        for a, b in zip(refs, refs[1:]):
            length += hav(pts[a], pts[b])
            if b in keep:
                u, v = (b, cur) if rev else (cur, b)
                e = dict(u=u, v=v, road=name or f"{cls} {wid}", cls=tags.get("highway"), speed=speed, one=1 if one else 0,
                         length=length, lanes=lanes, sp_src=sp_src, wid=wid)
                key = (u, v)
                if key not in seg or length < seg[key]["length"]:
                    seg[key] = e
                cur, length = b, 0.0
    return seg


def largest_component(seg):
    adj = defaultdict(list)
    for (u, v), e in seg.items():
        adj[u].append(v)
        if not e["one"]:
            adj[v].append(u)
    nodes = list(adj)
    for u, v in list(seg):
        adj.setdefault(v, [])
    comps = sorted(scc(list(adj), adj), key=len, reverse=True)
    return set(comps[0])


def write(pts, seg, out):
    os.makedirs(out, exist_ok=True)
    keepn = largest_component(seg)
    seg = {k: e for k, e in seg.items() if k[0] in keepn and k[1] in keepn}
    # drop reverse duplicates of two-way roads
    final, seen = [], set()
    for (u, v), e in seg.items():
        if not e["one"]:
            if (v, u) in seen:
                continue
            seen.add((u, v))
        final.append(e)
    used = sorted({e["u"] for e in final} | {e["v"] for e in final}, key=lambda r: (pts[r][1], pts[r][0]))
    nid = {r: f"N{i+1:04d}" for i, r in enumerate(used)}
    roads = defaultdict(set)
    for e in final:
        if not e["road"].split(" ")[0] in CLASS_ORDER:  # real name
            roads[e["u"]].add(e["road"]); roads[e["v"]].add(e["road"])
    with open(f"{out}/nodes.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["id", "name", "lat", "lon"])
        for r in used:
            names = sorted(roads[r])[:2]
            w.writerow([nid[r], " / ".join(names) if names else nid[r], round(pts[r][0], 6), round(pts[r][1], 6)])
    cols = ["from", "to", "road", "speed_limit_kmh", "oneway", "base_congestion", "blocked",
            "highway", "length_km", "lanes", "congestion_source", "speed_source", "osm_way_id"]
    with open(f"{out}/edges.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(cols)
        for e in final:
            cls = base_class(e["cls"])
            w.writerow([nid[e["u"]], nid[e["v"]], e["road"], e["speed"], e["one"], DEFAULT_CONG[cls], 0,
                        e["cls"], round(e["length"], 4), e["lanes"], "assumed_by_class", e["sp_src"], e["wid"]])
    return len(used), len(final)


def main():
    ap = argparse.ArgumentParser(description="OSM XML -> nodes.csv / edges.csv")
    ap.add_argument("osm")
    ap.add_argument("--out", default="data_osm")
    ap.add_argument("--min-class", default="tertiary", choices=CLASS_ORDER,
                    help="least important road class to keep (default tertiary)")
    a = ap.parse_args()
    pts, ways = read_osm(a.osm, a.min_class)
    print(f"read {len(pts)} map points, {len(ways)} usable roads")
    seg = build(pts, ways)
    n, m = write(pts, seg, a.out)
    print(f"wrote {a.out}/nodes.csv ({n} nodes) and edges.csv ({m} segments, largest connected part only)")


if __name__ == "__main__":
    main()
