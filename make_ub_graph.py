"""make_ub_graph.py - build data_ub/: a station graph of Ulaanbaatar from real OSM data.

Why: the original 15-node city graph (nodes.csv / edges.csv) has coordinates
written from memory and straight-line lengths x 1.3. It stays unchanged (all
Week XII-XV tests and reports use it). data_ub/ is the accurate version:

  * stations  : well-known places looked up BY NAME in OpenStreetMap
                (data_osm_raw/ub_places.json) - coordinates come from the map.
                A station's node sits on the road junction that serves the
                place (nodes.csv lat/lon); the place itself is place_lat/lon;
  * roads     : the real road network (data_osm_raw/ub_wide_tertiary.osm ->
                data_osm_wide/ via osm_to_graph.py);
  * links     : each station is joined to its nearest neighbour stations along
                the shortest REAL road path. A link that passes another station
                is dropped (it is A->C->B). Each direction is its own row, so
                one-way streets are respected;
  * per link  : real length, road names, OSM road class, and a speed limit /
                base congestion chosen so that the link's travel time equals the
                sum of the real road pieces;
  * geometry  : the road polyline of each link (data_ub/geometry.csv) so the
                visualizer draws real streets.

    python3 make_ub_graph.py           # writes data_ub/{nodes,edges,stations,geometry}.csv

Offline (uses the downloaded files). Data (c) OpenStreetMap contributors, ODbL.
"""
import csv
import heapq
import json
import math
import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from graph import Graph, haversine_km  # noqa: E402

PLACES = os.path.join(HERE, "data_osm_raw", "ub_places.json")
ROADS_OSM = os.path.join(HERE, "data_osm_raw", "ub_wide_tertiary.osm")
ROADS = os.path.join(HERE, "data_osm_wide")
OUT = os.path.join(HERE, "data_ub")
K_NEAREST = 5          # candidate links per station (by road distance)
SNAP_MAX_KM = 0.8      # a station must be this close to a road junction ...
SNAP_MAX_AREA_KM = 1.5  # ... except big areas (airport, park): their OSM point is the middle of the area


def snap_limit(kind, ref):
    return SNAP_MAX_AREA_KM if kind in ("airport", "park") and not ref.startswith("node/") else SNAP_MAX_KM
NEAR_STATION_KM = 0.15  # a link passing this close to another station is redundant

# (English name, kind, search terms matched against OSM name / name:en / name:mn / alt_name).
# Terms are OSM names, so the coordinates come from OpenStreetMap, not from memory.
STATIONS = []  # filled in below the functions (see STATION_SPEC)


def norm(s):
    return re.sub(r"[\s\-\.,'\"«»()]+", " ", (s or "").lower()).strip()


def load_places():
    data = json.load(open(PLACES, encoding="utf-8"))
    out = []
    for el in data["elements"]:
        tags = el.get("tags", {})
        if "lat" in el:
            lat, lon = el["lat"], el["lon"]
        elif "center" in el:
            lat, lon = el["center"]["lat"], el["center"]["lon"]
        else:
            continue
        names = [tags.get(k) for k in ("name", "name:en", "name:mn", "alt_name", "old_name", "int_name") if tags.get(k)]
        if names:
            out.append(dict(lat=lat, lon=lon, names=names, tags=tags, ref=f"{el['type']}/{el['id']}"))
    return out


def find_place(places, terms, kinds=None):
    """First OSM feature whose name matches a term (exact match preferred)."""
    nt = [norm(t) for t in terms]
    for exact in (True, False):
        for t in nt:
            for p in places:
                if kinds and not any(k in p["tags"] for k in kinds):
                    continue
                for n in p["names"]:
                    if (norm(n) == t) if exact else (t in norm(n)):
                        return p, n
    return None, None


def road_midpoint(g, terms):
    """Fallback for things that are roads (bridges): middle of the matching road segments."""
    nt = [norm(t) for t in terms]
    hits = [e for e in g.edges if any(t in norm(e["road"]) for t in nt)]
    if not hits:
        return None
    pts = [g.nodes[e[k]] for e in hits for k in ("src", "dst")]
    return dict(lat=sum(p[1] for p in pts) / len(pts), lon=sum(p[2] for p in pts) / len(pts),
                names=[hits[0]["road"]], tags={"highway": hits[0].get("highway")}, ref=f"road:{hits[0]['road']}")


def road_shapes():
    """Full street shape (every OSM shape point, not just junctions) of each road
    piece in data_osm_wide/edges.csv, recovered from the raw OSM ways:
    {(from, to): [(lat, lon), ...]} for both directions."""
    try:
        from defusedxml import ElementTree as ET
    except ImportError:
        import xml.etree.ElementTree as ET
    pts, ways = {}, {}
    for _, el in ET.iterparse(ROADS_OSM, events=("end",)):
        if el.tag == "node":
            pts[el.get("id")] = (float(el.get("lat")), float(el.get("lon")))
        elif el.tag == "way":
            ways[el.get("id")] = [n.get("ref") for n in el.findall("nd")]
            el.clear()
    key = lambda c: (round(c[0], 6), round(c[1], 6))
    nodes = {}
    with open(os.path.join(ROADS, "nodes.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            nodes[r["id"]] = (float(r["lat"]), float(r["lon"]))
    shapes = {}
    with open(os.path.join(ROADS, "edges.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            seq = [pts[n] for n in ways.get(r["osm_way_id"], []) if n in pts]
            ks = [key(c) for c in seq]
            a, b = key(nodes[r["from"]]), key(nodes[r["to"]])
            best = None
            for i in (i for i, k in enumerate(ks) if k == a):
                for j in (j for j, k in enumerate(ks) if k == b):
                    part = seq[i:j + 1] if i <= j else seq[j:i + 1][::-1]
                    ln = sum(haversine_km(*p, *q) for p, q in zip(part, part[1:]))
                    if best is None or abs(ln - float(r["length_km"])) < best[0]:
                        best = (abs(ln - float(r["length_km"])), part)
            shape = best[1] if best else [nodes[r["from"]], nodes[r["to"]]]
            shapes[(r["from"], r["to"])] = shape
            shapes.setdefault((r["to"], r["from"]), shape[::-1])
    return shapes


def dijkstra(g, src):
    dist, parent, pq, done = {src: 0.0}, {src: None}, [(0.0, src)], set()
    while pq:
        d, u = heapq.heappop(pq)
        if u in done:
            continue
        done.add(u)
        for e in g.adj[u]:
            v, nd = e["dst"], d + e["distance_km"]
            if nd < dist.get(v, float("inf")):
                dist[v], parent[v] = nd, (u, e)
                heapq.heappush(pq, (nd, v))
    return dist, parent


def path_edges(parent, dst):
    out, v = [], dst
    while parent[v] is not None:
        u, e = parent[v]
        out.append(e)
        v = u
    return out[::-1]


def link_attributes(edges):
    """One station-to-station link from the real road pieces along it."""
    length = sum(e["distance_km"] for e in edges)
    t_free = sum(e["distance_km"] / e["speed_kmh"] for e in edges)                       # h
    t_cong = sum(e["distance_km"] / (e["speed_kmh"] * (1 - 0.7 * e["congestion"])) for e in edges)
    speed = length / t_free
    cong = (1 - t_free / t_cong) / 0.7          # so that length / (speed (1-0.7c)) == t_cong
    by_name, by_class = defaultdict(float), defaultdict(float)
    for e in edges:
        if not re.match(r"^(motorway|trunk|primary|secondary|tertiary)(_link)? \d+$", e["road"]):
            by_name[e["road"]] += e["distance_km"]
        by_class[(e.get("highway") or "").replace("_link", "")] += e["distance_km"]
    names = [n for n, _ in sorted(by_name.items(), key=lambda kv: -kv[1])][:2]
    return dict(length=length, speed=speed, cong=cong, road=" / ".join(names) or "local road",
                highway=max(by_class, key=by_class.get) if by_class else "")


def build():
    if not os.path.exists(os.path.join(ROADS, "edges.csv")):
        import subprocess
        subprocess.run([sys.executable, os.path.join(HERE, "osm_to_graph.py"), ROADS_OSM, "--out", ROADS,
                        "--min-class", "tertiary"], check=True)
    roads = Graph().load(os.path.join(ROADS, "nodes.csv"), os.path.join(ROADS, "edges.csv"))
    places = load_places()

    # ---- 1. stations from OSM names
    stations, missing = [], []
    for sid, (name, kind, terms, keys) in enumerate(STATION_SPEC, 1):
        p, matched = find_place(places, terms, keys)
        if p is None and kind == "bridge":
            p = road_midpoint(roads, terms)
            matched = p and p["names"][0]
        if p is None:
            missing.append(name)
            continue
        stations.append(dict(name=name, kind=kind, lat=p["lat"], lon=p["lon"], osm=p["ref"], osm_name=matched))

    # ---- 2. snap to the nearest road junction
    rid = list(roads.nodes)
    for s in stations:
        best = min(rid, key=lambda r: (roads.nodes[r][1] - s["lat"]) ** 2 + ((roads.nodes[r][2] - s["lon"]) * 0.67) ** 2)
        s["road_node"] = best
        s["snap_km"] = haversine_km(s["lat"], s["lon"], roads.nodes[best][1], roads.nodes[best][2])
    dropped = [f"{s['name']} ({s['snap_km']:.1f} km from a road)" for s in stations
               if s["snap_km"] > snap_limit(s["kind"], s["osm"])]
    stations = [s for s in stations if s["snap_km"] <= snap_limit(s["kind"], s["osm"])]
    # two stations on the same junction: keep the first
    seen, uniq = set(), []
    for s in stations:
        if s["road_node"] in seen:
            dropped.append(s["name"] + " (same junction)")
            continue
        seen.add(s["road_node"]); uniq.append(s)
    stations = uniq
    for i, s in enumerate(stations, 1):
        s["id"] = f"U{i:02d}"
    at = {s["road_node"]: s for s in stations}

    # ---- 3. links along real roads
    links = {}
    for s in stations:
        dist, parent = dijkstra(roads, s["road_node"])
        cands = sorted(((dist[o["road_node"]], o) for o in stations if o is not s and o["road_node"] in dist),
                       key=lambda x: x[0])
        for d, o in cands[:K_NEAREST]:
            pe = path_edges(parent, o["road_node"])
            inner = [e["dst"] for e in pe[:-1]]
            if any(n in at for n in inner):
                continue  # another station is on the way
            near = [x for x in stations if x is not s and x is not o and any(
                haversine_km(roads.nodes[n][1], roads.nodes[n][2], x["lat"], x["lon"]) < NEAR_STATION_KM for n in inner)]
            if near:
                continue
            links[(s["id"], o["id"])] = (pe, link_attributes(pe))
    # make every link usable both ways if the road allows it
    for (a, b) in list(links):
        if (b, a) not in links:
            sa = next(s for s in stations if s["id"] == b)
            sb = next(s for s in stations if s["id"] == a)
            dist, parent = dijkstra(roads, sa["road_node"])
            if sb["road_node"] in dist:
                pe = path_edges(parent, sb["road_node"])
                links[(b, a)] = (pe, link_attributes(pe))

    # ---- 4. write
    shapes = road_shapes()
    os.makedirs(OUT, exist_ok=True)
    # node position = the road junction that serves the place (so road lengths are exact and
    # A*'s straight-line heuristic matches the network); the place itself is kept as place_lat/lon
    with open(os.path.join(OUT, "nodes.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["id", "name", "lat", "lon", "kind", "place_lat", "place_lon"])
        for s in stations:
            _, jla, jlo = roads.nodes[s["road_node"]]
            w.writerow([s["id"], s["name"], jla, jlo, s["kind"], round(s["lat"], 6), round(s["lon"], 6)])
    with open(os.path.join(OUT, "stations.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["id", "name", "kind", "place_lat", "place_lon", "junction_lat", "junction_lon",
                                       "osm_feature", "osm_name", "snap_km"])
        for s in stations:
            _, jla, jlo = roads.nodes[s["road_node"]]
            w.writerow([s["id"], s["name"], s["kind"], round(s["lat"], 6), round(s["lon"], 6), jla, jlo, s["osm"],
                        s["osm_name"], round(s["snap_km"], 3)])
    cols = ["from", "to", "road", "speed_limit_kmh", "oneway", "base_congestion", "blocked", "highway", "length_km",
            "congestion_source", "speed_source"]
    with open(os.path.join(OUT, "edges.csv"), "w", newline="", encoding="utf-8") as f, \
            open(os.path.join(OUT, "geometry.csv"), "w", newline="", encoding="utf-8") as fg:
        w, wg = csv.writer(f), csv.writer(fg)
        w.writerow(cols); wg.writerow(["from", "to", "points"])
        for (a, b), (pe, at_) in sorted(links.items()):
            w.writerow([a, b, at_["road"], round(at_["speed"], 2), 1, round(at_["cong"], 4), 0, at_["highway"],
                        round(at_["length"], 4), "osm_class_default", "osm_length_weighted"])
            pts = [roads.nodes[pe[0]["src"]][1:]]
            for e in pe:
                pts += shapes.get((e["src"], e["dst"]), [roads.nodes[e["src"]][1:], roads.nodes[e["dst"]][1:]])[1:]
            wg.writerow([a, b, ";".join(f"{la:.6f} {lo:.6f}" for la, lo in pts)])
    return stations, links, missing, dropped


# ------------------------------------------------------------------ station list
# name shown in the app, kind, OSM search terms (Mongolian / English, as they appear in OSM),
# optional tag keys the feature must have (None = any).
STATION_SPEC = [
    # centre and landmarks
    ("Sukhbaatar Square", "square", ["Сүхбаатарын талбай"], ["place"]),
    ("Gandan Monastery", "monastery", ["Мэгжид Жанрайсиг сүм"], None),
    ("Choijin Lama Temple", "museum", ["Чойжин ламын сүм музей"], None),
    ("National Museum", "museum", ["Монголын үндэсний түүхийн музей"], None),
    ("Drama Theatre", "theatre", ["Улсын драмын Эрдмийн театр"], None),
    ("Dashchoilin Monastery", "monastery", ["Дашчойлин хийд"], None),
    ("Arts and Culture University", "university", ["Соёл Урлагын Их Сургууль"], None),
    ("Medical Sciences University", "university", ["Анагаахын Шинжлэх Ухааны Үндэсний Их Сургууль"], None),
    ("Railway University", "university", ["Төмөр замын их сургууль"], None),
    ("Peace Bridge", "bridge", ["Peace Bridge"], None),
    ("Central Stadium", "stadium", ["Төв цэнгэлдэх хүрээлэн"], None),
    ("Bogd Khan Palace", "museum", ["Богд хааны ордон музей"], None),
    ("Zaisan Memorial", "memorial", ["Зайсан толгой"], None),
    ("Natural History Museum", "museum", ["Байгалийн түүхийн музей"], None),
    ("National Park", "park", ["Үндэсний Цэцэрлэгт Хүрээлэн"], None),
    ("Zhukov Museum", "museum", ["Жуковын Музей"], None),
    ("Officers' Roundabout", "square", ["Офицерийн тойрог"], None),
    ("Astronomical Observatory", "museum", ["Ulaanbaatar Astronomical Observatory"], None),
    # markets and malls
    ("Narantuul Market", "market", ["Нарантуул зах"], None),
    ("Kharkhorin Market", "market", ["Хархорин"], ["amenity"]),
    ("Bayangol Market", "market", ["Баянгол Зах"], None),
    ("Amgalan Market", "market", ["Амгалан зах"], None),
    ("Khuchit Shonkhor Market", "market", ["Хүчит шонхор зах"], None),
    ("Bars Trade Center", "market", ["Барс 2 худалдааны төв"], None),
    ("Ogooj Market", "market", ["Өгөөж зах"], None),
    ("Belkh Market", "market", ["Belkh zakh"], None),
    ("Metro Mall", "mall", ["Metro mall"], None),
    ("Millennium Mall", "mall", ["Millennium mall"], None),
    ("Home Plaza", "mall", ["Home Plaza"], None),
    ("Max Mall", "mall", ["Max Mall"], None),
    ("Bombogor Center", "mall", ["Бөмбөгөр худалдааны төв-1"], None),
    # transport
    ("Ulaanbaatar Railway Station", "station", ["Улаанбаатар"], ["railway"]),
    ("Tolgoit Station", "station", ["Толгойт"], ["railway"]),
    ("Amgalan Station", "station", ["Амгалан"], ["railway"]),
    ("Buyant-Ukhaa Airport", "airport", ["Буянт-Ухаа олон улсын нисэх онгоцны буудал"], ["aeroway"]),
    ("Dragon Bus Terminal", "bus terminal", ["Драгон"], ["amenity"]),
    ("Bayanzurkh Bus Terminal", "bus terminal", ["Баянзүрх авто вокзал"], None),
    ("Lavai Bus Terminal", "bus terminal", ["Лавай авто буудал"], None),
    ("Dunjingarav", "bus terminal", ["Дүнжингарав зогсоол"], None),
    ("Trauma Hospital", "hospital", ["Гэмтэлийн эмнэлэг"], None),
    ("Khan-Uul Hospital", "hospital", ["Khan uul duurgiin Emneleg"], None),
    ("Buyant-Ukhaa Sports Complex", "stadium", ["Буянт-Ухаа Спорт Цогцолбор"], None),
    # districts (OSM place=suburb)
    ("Yarmag", "district", ["Яармаг"], ["place"]),
    ("Nisekh", "district", ["Нисэх"], ["place"]),
    ("Bayankhoshuu", "district", ["Баянхошуу"], ["place"]),
    ("Dambadarjaa", "district", ["Дамбадаржаа"], ["place"]),
    ("Sharkhad", "district", ["Шархад"], ["place"]),
    ("Ulaankhuaran", "district", ["Улаанхуаран"], ["place"]),
    ("Dari-Ekh", "district", ["Дарь-Эх"], ["place"]),
    ("1st Microdistrict", "district", ["1-р хороолол"], ["place"]),
    ("Orbit", "district", ["Орбит"], ["place"]),
    ("Biokombinat", "district", ["Биокомбинат"], ["place"]),
    ("Chingeltei", "district", ["Чингэлтэй"], ["place"]),
    ("Uliastai", "district", ["Улиастай"], ["place"]),
    ("Tsaiz", "district", ["Цайз"], ["place"]),
    ("Zuun Salaa", "district", ["Зүүн салаа"], ["place"]),
]


def main():
    stations, links, missing, dropped = build()
    print(f"stations: {len(stations)} (not found in OSM: {missing or 'none'}; dropped: {dropped or 'none'})")
    print(f"links: {len(links)} directed, written to {OUT}/")
    worst = max(stations, key=lambda s: s["snap_km"])
    print(f"largest snap distance: {worst['name']} {worst['snap_km'] * 1000:.0f} m")


if __name__ == "__main__":
    main()
