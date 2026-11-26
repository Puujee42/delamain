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
  * links     : a greedy spanner over the real road network: station pairs are
                taken from the closest to the farthest and the real shortest road
                A->B is added only if the links so far cannot already do it within
                5 % (STRETCH). Sparse, and every station-to-station distance is within
                5 % of the real road distance. Each direction is its own row;
  * per link  : real length, road names, OSM road class, and a speed limit /
                base congestion chosen so that the link's travel time equals the
                sum of the real road pieces;
  * geometry  : the road polyline of each link (data_ub/geometry.csv) so the
                visualizer draws real streets.

    python3 make_ub_graph.py                 # all three levels
    python3 make_ub_graph.py --level small   # data_ub/   53 landmarks
    python3 make_ub_graph.py --level medium  # data_ub_m/ + other named OSM places (markets, malls, ...)
    python3 make_ub_graph.py --level large   # data_ub_l/ + named bus stops
    python3 make_ub_graph.py --level full    # data_ub_full/ every street junction + all stations (exact)
  each writes {nodes,edges,stations,geometry}.csv

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
OUT = os.path.join(HERE, "data_ub")  # small level (see LEVELS)
STRETCH = 1.05         # station-graph distance <= 1.05 x real road distance for every pair
SNAP_MAX_KM = 0.8      # a station must be this close to a road junction ...
SNAP_MAX_AREA_KM = 1.5  # ... except big areas (airport, park): their OSM point is the middle of the area


def snap_limit(kind, ref):
    return SNAP_MAX_AREA_KM if kind in ("airport", "park") and not ref.startswith("node/") else SNAP_MAX_KM

# (English name, kind, search terms matched against OSM name / name:en / name:mn / alt_name).
# Terms are OSM names, so the coordinates come from OpenStreetMap, not from memory.
STATIONS = []  # filled in below the functions (see STATION_SPEC)


def norm(s):
    return re.sub(r"[\s\-\.,'\"«»()]+", " ", (s or "").lower()).strip()


def load_places(path=None):
    data = json.load(open(path or PLACES, encoding="utf-8"))
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


def road_pieces(osm_file=None, roads_dir=None):
    """For every road piece in <roads_dir>/edges.csv, recovered from the raw OSM ways:
      shapes  {(from, to): [(lat, lon), ...]}  full street shape (every OSM shape point)
      signals {(from, to): n}                  traffic lights met on the way: a junction light
              (OSM highway=traffic_signals) counts 1, a pedestrian-crossing light
              (crossing=traffic_signals) counts 0.5 (short cycle, often green for cars).
              A light counts on the piece that ARRIVES at it, so once per trip.
    Both directions are filled in."""
    try:
        from defusedxml import ElementTree as ET
    except ImportError:
        import xml.etree.ElementTree as ET
    pts, ways, lights = {}, {}, {}
    osm_file, roads_dir = osm_file or ROADS_OSM, roads_dir or ROADS
    for _, el in ET.iterparse(osm_file, events=("end",)):
        if el.tag == "node":
            pts[el.get("id")] = (float(el.get("lat")), float(el.get("lon")))
            tags = {t.get("k"): t.get("v") for t in el.findall("tag")}
            if tags.get("highway") == "traffic_signals":
                lights[el.get("id")] = 1.0
            elif tags.get("crossing") == "traffic_signals" or tags.get("crossing:signals") == "yes":
                lights[el.get("id")] = 0.5
            el.clear()
        elif el.tag == "way":
            ways[el.get("id")] = [n.get("ref") for n in el.findall("nd")]
            el.clear()
    key = lambda c: (round(c[0], 6), round(c[1], 6))
    nodes = {}
    with open(os.path.join(roads_dir, "nodes.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            nodes[r["id"]] = (float(r["lat"]), float(r["lon"]))
    shapes, signals = {}, {}
    with open(os.path.join(roads_dir, "edges.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ids = [n for n in ways.get(r["osm_way_id"], []) if n in pts]
            seq = [pts[n] for n in ids]
            ks = [key(c) for c in seq]
            a, b = key(nodes[r["from"]]), key(nodes[r["to"]])
            best = None
            for i in (i for i, k in enumerate(ks) if k == a):
                for j in (j for j, k in enumerate(ks) if k == b):
                    part = seq[i:j + 1] if i <= j else seq[j:i + 1][::-1]
                    pids = ids[i:j + 1] if i <= j else ids[j:i + 1][::-1]
                    ln = sum(haversine_km(*p, *q) for p, q in zip(part, part[1:]))
                    if best is None or abs(ln - float(r["length_km"])) < best[0]:
                        best = (abs(ln - float(r["length_km"])), part, pids)
            L = float(r["length_km"])
            if best and best[0] > max(0.1 * L, 0.02):  # e.g. a loop: no part of the way fits, draw it straight
                best = (best[0], [nodes[r["from"]], nodes[r["to"]]], [best[2][0], best[2][-1]])
            shape, pids = (best[1], best[2]) if best else ([nodes[r["from"]], nodes[r["to"]]], [])
            shapes[(r["from"], r["to"])] = shape
            shapes.setdefault((r["to"], r["from"]), shape[::-1])
            signals[(r["from"], r["to"])] = sum(lights.get(n, 0.0) for n in pids[1:])
            signals.setdefault((r["to"], r["from"]), sum(lights.get(n, 0.0) for n in pids[:-1]))
    return shapes, signals


def road_shapes(osm_file=None, roads_dir=None):
    return road_pieces(osm_file, roads_dir)[0]


def dijkstra(g, src, stop_at=None):
    """Shortest road distances from src. Nodes in stop_at (other stations) are
    reached but not expanded."""
    dist, parent, pq, done = {src: 0.0}, {src: None}, [(0.0, src)], set()
    while pq:
        d, u = heapq.heappop(pq)
        if u in done:
            continue
        done.add(u)
        if stop_at and u != src and u in stop_at:
            continue
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


def link_attributes(edges, signals=None):
    """One station-to-station link from the real road pieces along it."""
    length = sum(e["distance_km"] for e in edges)
    lights = sum((signals or {}).get((e["src"], e["dst"]), 0) for e in edges)
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
                highway=max(by_class, key=by_class.get) if by_class else "", signals=lights)


LEVELS = {"small": "data_ub", "medium": "data_ub_m", "large": "data_ub_l", "full": "data_ub_full"}
# full level: the routing graph IS the full street network (residential streets too); stations are
# named junctions on it, so routes are exact (no station-to-station approximation)
TILES = os.path.join(HERE, "data_osm_raw", "tiles")  # the street download comes in 4 tiles
ROADS_ALL_OSM = os.path.join(HERE, "data_osm_raw", "ub_wide_all.osm")
ROADS_ALL = os.path.join(HERE, "data_osm_all")
PLACES_MORE = os.path.join(HERE, "data_osm_raw", "ub_places_more.json")
# (shop=supermarket is left out on purpose: in UB's OSM data most of them are small corner shops,
#  and big stores are already in the medium level as malls / markets)
MORE_CATEGORIES = [("amenity", "school", "school"), ("amenity", "college", "college"),
                   ("amenity", "kindergarten", "kindergarten"), ("tourism", "hotel", "hotel"),
                   ("amenity", "fuel", "petrol station"),
                   ("leisure", "park", "park"), ("leisure", "sports_centre", "sports centre"),
                   ("amenity", "cinema", "cinema"), ("amenity", "library", "library"),
                   ("amenity", "police", "police"), ("amenity", "fire_station", "fire station"),
                   ("amenity", "post_office", "post office"), ("amenity", "embassy", "embassy"),
                   ("amenity", "community_centre", "community centre")]
FULL_SPACING_KM = 0.25      # full level: places at least this far apart (denser than medium)
FULL_STOP_SPACING_KM = 0.15  # bus stops
FULL_STOP_SNAP_KM = 0.15     # with every street in the network a stop must be right on a road
FULL_POI_SNAP_KM = 0.4
STOPS = os.path.join(HERE, "data_osm_raw", "ub_stops.json")
POI_SPACING_KM = 0.4    # medium: an extra place must be this far from every station already chosen
STOP_SPACING_KM = 0.25  # large: same for bus stops
STOP_SNAP_KM = 0.4      # bus stops stand on roads
# medium level: OSM categories that become stations (in this priority order) -> kind
POI_CATEGORIES = [("place", "suburb", "district"), ("amenity", "marketplace", "market"), ("shop", "mall", "mall"),
                  ("amenity", "university", "university"), ("tourism", "museum", "museum"),
                  ("amenity", "theatre", "theatre"), ("amenity", "bus_station", "bus terminal"),
                  ("amenity", "hospital", "hospital"), ("leisure", "stadium", "stadium"),
                  ("amenity", "place_of_worship", "temple"), ("tourism", "attraction", "attraction")]
# names that are a type of shop, not a place ("grocery store", "pharmacy", "playground", ...)
GENERIC = re.compile(r"хүнсний|хүсний|ногооны|барааны дэлгүүр|^дэлгүүр$|эмийн сан|тоглоомын талбай|сагсан бөмбөг|"
                     r"машины зогсоол|шүдний|^зах$|^temple$|^museum$|^cym$|^сүм ?\d*$|^\d+|"
                     r"^(cu|gs25|circle k|egg mart)\b|(?<!их )дэлгүүр$", re.I)


GENERIC_FULL = re.compile(GENERIC.pattern.replace("|^\\d+|", "|^\\d+$|"), re.I)


def clean_name(tags):
    """Readable station name: English if OSM has it, else the Mongolian name
    (vertical Mongolian script and ';' alternatives removed)."""
    en = tags.get("name:en", "")
    n = en if en and en.isascii() else tags.get("name", "")
    readable = lambda x: not re.search(r"[^\u0000-ɏЀ-ӿ᠀-᢯‐-⁯«»№]", x)
    if not readable(n):  # e.g. a Korean or Chinese name: use the Mongolian one, or skip the place
        n = next((tags[k] for k in ("name:mn", "alt_name") if tags.get(k) and readable(tags[k])), "")
    n = re.sub(r"[᠀-᢯]+", "", n).split(";")[0]
    n = re.sub(r"[\"«»“”]", "", n)
    return re.sub(r"\s+", " ", n).strip()


class Grid:
    """Points in ~250 m cells, for 'is any station near here?' queries."""

    def __init__(self, cell=0.0025):
        self.cell, self.cells = cell, defaultdict(list)

    def key(self, la, lo):
        return int(la / self.cell), int(lo / (self.cell / 0.67))

    def add(self, la, lo, item):
        self.cells[self.key(la, lo)].append((la, lo, item))

    def near(self, la, lo, km):
        r = int(km / (self.cell * 111)) + 1
        ki, kj = self.key(la, lo)
        for i in range(ki - r, ki + r + 1):
            for j in range(kj - r, kj + r + 1):
                for pla, plo, item in self.cells.get((i, j), ()):
                    if haversine_km(la, lo, pla, plo) < km:
                        yield item


def landmark_stations(roads, places):
    out, missing = [], []
    for name, kind, terms, keys in STATION_SPEC:
        p, matched = find_place(places, terms, keys)
        if p is None and kind == "bridge":
            p = road_midpoint(roads, terms)
            matched = p and p["names"][0]
        if p is None:
            missing.append(name)
            continue
        out.append(dict(name=name, kind=kind, lat=p["lat"], lon=p["lon"], osm=p["ref"], osm_name=matched, prefix="U",
                        snap_max=None))
    return out, missing


def extra_places(places, taken, categories=None, spacing=None, generic=None, snap=None):
    """Medium level: every other suitable named OSM place, spaced out."""
    categories, spacing = categories or POI_CATEGORIES, spacing or POI_SPACING_KM
    generic, snap = generic or GENERIC, snap or SNAP_MAX_KM
    grid = Grid()
    for s in taken:
        grid.add(s["lat"], s["lon"], s)
    names = defaultdict(int)
    for p in places:
        names[norm(clean_name(p["tags"]))] += 1
    out = []
    for key, val, kind in categories:
        for p in places:
            if p["tags"].get(key) != val:
                continue
            nm = clean_name(p["tags"])
            if len(nm) < 3 or generic.search(nm) or (names[norm(nm)] > 2 and kind != "district"):
                continue
            if any(True for _ in grid.near(p["lat"], p["lon"], spacing)):
                continue
            s = dict(name=nm, kind=kind, lat=p["lat"], lon=p["lon"], osm=p["ref"], osm_name=p["tags"].get("name", nm),
                     prefix="P", snap_max=snap)
            out.append(s)
            grid.add(s["lat"], s["lon"], s)
    return out


def bus_stops(taken, spacing=None, snap=None):
    """Large level: named bus stops. Same-name stops on both sides of a road
    (within 400 m) become one station at their mean position."""
    els = json.load(open(STOPS, encoding="utf-8"))["elements"]
    groups = []
    for el in els:
        nm = clean_name(el.get("tags", {}))
        if len(nm) < 2 or GENERIC.search(nm):
            continue
        for g_ in groups:
            if g_["key"] == norm(nm) and haversine_km(g_["lat"], g_["lon"], el["lat"], el["lon"]) < 0.4:
                g_["pts"].append((el["lat"], el["lon"])); g_["refs"].append(f"node/{el['id']}")
                g_["lat"] = sum(a for a, _ in g_["pts"]) / len(g_["pts"])
                g_["lon"] = sum(b for _, b in g_["pts"]) / len(g_["pts"])
                break
        else:
            groups.append(dict(key=norm(nm), name=nm, lat=el["lat"], lon=el["lon"], pts=[(el["lat"], el["lon"])],
                               refs=[f"node/{el['id']}"], osm_name=el["tags"].get("name", nm)))
    grid = Grid()
    for s in taken:
        grid.add(s["lat"], s["lon"], s)
    out = []
    for g_ in groups:
        if any(True for _ in grid.near(g_["lat"], g_["lon"], spacing or STOP_SPACING_KM)):
            continue
        s = dict(name=g_["name"], kind="bus stop", lat=g_["lat"], lon=g_["lon"], osm="+".join(g_["refs"][:3]),
                 osm_name=g_["osm_name"], prefix="B", snap_max=snap or STOP_SNAP_KM)
        out.append(s)
        grid.add(s["lat"], s["lon"], s)
    return out


def components(ids, links):
    adj = defaultdict(list)
    for a, b in links:
        adj[a].append(b)
    from audit import scc
    for i in ids:
        adj.setdefault(i, [])
    return sorted(scc(list(ids), adj), key=len, reverse=True)


def merge_tiles():
    """Join the 4 downloaded street tiles into one OSM file (each node and way once)."""
    try:
        from defusedxml import ElementTree as ET
    except ImportError:
        import xml.etree.ElementTree as ET
    from glob import glob
    from xml.sax.saxutils import quoteattr
    nodes, ways = {}, {}
    for tile in sorted(glob(os.path.join(TILES, "streets_*.osm"))):
        for _, el in ET.iterparse(tile, events=("end",)):
            if el.tag == "node":
                nodes[el.get("id")] = (el.get("lat"), el.get("lon"), [(t.get("k"), t.get("v")) for t in el.findall("tag")])
                el.clear()
            elif el.tag == "way":
                ways[el.get("id")] = ([n.get("ref") for n in el.findall("nd")],
                                      [(t.get("k"), t.get("v")) for t in el.findall("tag")])
                el.clear()
    if not ways:
        raise SystemExit("no street tiles in data_osm_raw/tiles/ - run fetch_osm_ub.sh first")
    tag = lambda kv: "".join(f"\n    <tag k={quoteattr(k)} v={quoteattr(v)}/>" for k, v in kv)
    with open(ROADS_ALL_OSM, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<osm version="0.6" generator="make_ub_graph.merge_tiles">\n'
                "<note>The data included in this document is from www.openstreetmap.org. "
                "The data is made available under ODbL.</note>\n")
        for i, (la, lo, kv) in nodes.items():
            f.write(f'  <node id="{i}" lat="{la}" lon="{lo}"' + (f">{tag(kv)}\n  </node>\n" if kv else "/>\n"))
        for i, (refs, kv) in ways.items():
            f.write(f'  <way id="{i}">' + "".join(f'\n    <nd ref="{r}"/>' for r in refs) + tag(kv) + "\n  </way>\n")
        f.write("</osm>\n")
    return len(nodes), len(ways)


def ensure_roads(full=False):
    if full and not os.path.exists(ROADS_ALL_OSM):
        merge_tiles()
    osm_file, folder, cls = (ROADS_ALL_OSM, ROADS_ALL, "residential") if full else (ROADS_OSM, ROADS, "tertiary")
    if not os.path.exists(os.path.join(folder, "edges.csv")):
        import subprocess
        subprocess.run([sys.executable, os.path.join(HERE, "osm_to_graph.py"), osm_file, "--out", folder,
                        "--min-class", cls], check=True)
    return Graph().load(os.path.join(folder, "nodes.csv"), os.path.join(folder, "edges.csv"))


def select_stations(level, roads, places):
    """Stations of a level, each snapped to the road junction that serves it, with ids and unique names."""
    full = level == "full"
    stations, missing = landmark_stations(roads, places)
    grid_r = Grid()
    for r, (_, la, lo) in roads.nodes.items():
        grid_r.add(la, lo, r)

    def snap(s):
        cand = list(grid_r.near(s["lat"], s["lon"], 0.6)) or list(roads.nodes)
        best = min(cand, key=lambda r: (roads.nodes[r][1] - s["lat"]) ** 2 + ((roads.nodes[r][2] - s["lon"]) * 0.67) ** 2)
        s["road_node"] = best
        s["snap_km"] = haversine_km(s["lat"], s["lon"], roads.nodes[best][1], roads.nodes[best][2])

    dropped = []

    def keep(group):
        ok = []
        for s in group:
            snap(s)
            lim = s["snap_max"] or snap_limit(s["kind"], s["osm"])
            if s["snap_km"] > lim:
                dropped.append(f"{s['name']} ({s['snap_km']:.1f} km from a road)")
            else:
                ok.append(s)
        return ok

    stations = keep(stations)
    if full:
        # a landmark serves the same place on every level: keep its small-level junction (main
        # roads are part of the full network too). Otherwise e.g. the airport would snap to a
        # small street on the far side of the airfield.
        small_st = os.path.join(HERE, LEVELS["small"], "stations.csv")
        if os.path.exists(small_st):
            at = {(round(la, 6), round(lo, 6)): n for n, (_, la, lo) in roads.nodes.items()}
            with open(small_st, encoding="utf-8") as f:
                junction = {r["name"]: (round(float(r["junction_lat"]), 6), round(float(r["junction_lon"]), 6))
                            for r in csv.DictReader(f)}
            for s in stations:
                n = at.get(junction.get(s["name"]))
                if n:
                    s["road_node"] = n
                    s["snap_km"] = haversine_km(s["lat"], s["lon"], roads.nodes[n][1], roads.nodes[n][2])
    if level in ("medium", "large"):
        stations += keep(extra_places(places, stations))
    if full:
        stations += keep(extra_places(places, stations, None, FULL_SPACING_KM, None, FULL_POI_SNAP_KM))
        stations += keep(bus_stops(stations, FULL_STOP_SPACING_KM, FULL_STOP_SNAP_KM))  # stops before schools etc.
        stations += keep(extra_places(load_places(PLACES_MORE), stations, MORE_CATEGORIES, FULL_SPACING_KM,
                                      GENERIC_FULL, FULL_POI_SNAP_KM))
    if level == "large":
        stations += keep(bus_stops(stations))
    # two stations on the same junction: keep the first (landmarks come first)
    seen, uniq = set(), []
    for s in stations:
        if s["road_node"] in seen:
            dropped.append(s["name"] + " (same junction)")
            continue
        seen.add(s["road_node"]); uniq.append(s)
    stations = uniq
    # full: landmarks keep their small-level id; landmarks that only fit on the full street network
    # (e.g. Chingeltei) get the next free numbers
    small_ids = {}
    if full and os.path.exists(os.path.join(HERE, LEVELS["small"], "nodes.csv")):
        with open(os.path.join(HERE, LEVELS["small"], "nodes.csv"), encoding="utf-8") as f:
            small_ids = {r["name"]: r["id"] for r in csv.DictReader(f)}
    count, used_names, next_u = defaultdict(int), set(), len(small_ids)
    for s in stations:
        count[s["prefix"]] += 1
        if full and s["prefix"] == "U":
            if s["name"] not in small_ids:
                next_u += 1
            s["id"] = small_ids.get(s["name"]) or f"U{next_u:02d}"
        elif s["prefix"] == "U":
            s["id"] = f"U{count['U']:02d}"
        else:
            s["id"] = f"{s['prefix']}{count[s['prefix']]:04d}" if full else f"{s['prefix']}{count[s['prefix']]:03d}"
        base, k = s["name"], 2
        while s["name"] in used_names:  # unique names: "Name (2)"
            s["name"] = f"{base} ({k})"; k += 1
        used_names.add(s["name"])
    return stations, missing, dropped


def write_stations(out, stations, roads, extra_nodes=()):
    """nodes.csv (stations first, then extra junction rows) and stations.csv."""
    # node position = the road junction that serves the place (so road lengths are exact and
    # A*'s straight-line heuristic matches the network); the place itself is kept as place_lat/lon
    with open(os.path.join(out, "nodes.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["id", "name", "lat", "lon", "kind", "place_lat", "place_lon"])
        for s in stations:
            _, jla, jlo = roads.nodes[s["road_node"]]
            w.writerow([s["id"], s["name"], jla, jlo, s["kind"], round(s["lat"], 6), round(s["lon"], 6)])
        for row in extra_nodes:
            w.writerow(row)
    with open(os.path.join(out, "stations.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["id", "name", "kind", "place_lat", "place_lon", "junction_lat", "junction_lon",
                                       "osm_feature", "osm_name", "snap_km"])
        for s in stations:
            _, jla, jlo = roads.nodes[s["road_node"]]
            w.writerow([s["id"], s["name"], s["kind"], round(s["lat"], 6), round(s["lon"], 6), jla, jlo, s["osm"],
                        s["osm_name"], round(s["snap_km"], 3)])


EDGE_COLS = ["from", "to", "road", "speed_limit_kmh", "oneway", "base_congestion", "blocked", "highway", "length_km",
             "congestion_source", "speed_source", "signals"]


def build(level="small", roads=None, places=None, pieces=None):
    """small / medium / large: a station graph whose links are real road paths (greedy spanner)."""
    if level == "full":
        return build_full(places)
    roads = roads or ensure_roads(False)
    places = places or load_places()
    shapes, sig = pieces or road_pieces()
    stations, missing, dropped = select_stations(level, roads, places)
    by_id = {s["id"]: s for s in stations}

    # ---- links along real roads: greedy spanner
    # Go through all station pairs from the closest to the farthest (by real road distance) and add
    # the road A->B only if the links so far cannot already get from A to B within STRETCH x the real
    # road distance. Sparse, every link is a real road path, and EVERY station-to-station distance on
    # the station graph is within STRETCH of the real road distance (tested).
    trees = {}

    def tree(s):
        if s["id"] not in trees:
            trees[s["id"]] = dijkstra(roads, s["road_node"])
        return trees[s["id"]]

    road_d = {}
    for s in stations:
        dist, _ = tree(s)
        for o in stations:
            if o is not s and o["road_node"] in dist:
                road_d[(s["id"], o["id"])] = dist[o["road_node"]]
    links, sadj = {}, defaultdict(dict)

    def graph_dist(a, b, limit):
        """Shortest distance a->b on the links added so far, giving up beyond limit."""
        d, pq, done = {a: 0.0}, [(0.0, a)], set()
        while pq:
            x, u = heapq.heappop(pq)
            if u == b:
                return x
            if u in done or x > limit:
                continue
            done.add(u)
            for v, w in sadj[u].items():
                if x + w < d.get(v, float("inf")) and x + w <= limit:
                    d[v] = x + w
                    heapq.heappush(pq, (x + w, v))
        return float("inf")

    for (a, b), d in sorted(road_d.items(), key=lambda kv: kv[1]):
        if graph_dist(a, b, STRETCH * d) <= STRETCH * d + 1e-12:
            continue
        dist, parent = tree(by_id[a])
        pe = path_edges(parent, by_id[b]["road_node"])
        links[(a, b)] = (pe, link_attributes(pe, sig))
        sadj[a][b] = d

    def add_back(pairs):
        for (a, b) in pairs:
            if (b, a) not in links:
                dist, parent = tree(by_id[b])
                if by_id[a]["road_node"] in dist:
                    pe = path_edges(parent, by_id[a]["road_node"])
                    links[(b, a)] = (pe, link_attributes(pe, sig))

    # ---- connectivity repair: join every smaller component to its nearest outside station
    for _ in range(len(stations)):
        comps = components([s["id"] for s in stations], links)
        if len(comps) == 1:
            break
        comp = set(comps[-1])
        best = None
        for a in comp:
            dist, _ = tree(by_id[a])
            for o in stations:
                if o["id"] not in comp and o["road_node"] in dist and (best is None or dist[o["road_node"]] < best[0]):
                    best = (dist[o["road_node"]], a, o["id"])
        if best is None:
            dropped += [by_id[i]["name"] + " (no road to the rest)" for i in comp]
            stations = [s for s in stations if s["id"] not in comp]
            links = {k: v for k, v in links.items() if k[0] not in comp and k[1] not in comp}
            continue
        _, a, b = best
        dist, parent = tree(by_id[a])
        pe = path_edges(parent, by_id[b]["road_node"])
        links[(a, b)] = (pe, link_attributes(pe, sig))
        add_back([(a, b)])
        if (b, a) not in links:  # one-way only: also link b to the nearest station in comp
            dist, parent = tree(by_id[b])
            tgt = min((x for x in comp if by_id[x]["road_node"] in dist), key=lambda x: dist[by_id[x]["road_node"]])
            pe = path_edges(parent, by_id[tgt]["road_node"])
            links[(b, tgt)] = (pe, link_attributes(pe, sig))

    # ---- write
    out = os.path.join(HERE, LEVELS[level])
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "roads_source.txt"), "w", encoding="utf-8") as f:
        f.write(os.path.basename(ROADS) + "\n")  # road network drawn as the visualizer background
    write_stations(out, stations, roads)
    with open(os.path.join(out, "edges.csv"), "w", newline="", encoding="utf-8") as f, \
            open(os.path.join(out, "geometry.csv"), "w", newline="", encoding="utf-8") as fg:
        w, wg = csv.writer(f), csv.writer(fg)
        w.writerow(EDGE_COLS); wg.writerow(["from", "to", "points"])
        for (a, b), (pe, at_) in sorted(links.items()):
            w.writerow([a, b, at_["road"], round(at_["speed"], 2), 1, round(at_["cong"], 4), 0, at_["highway"],
                        round(at_["length"], 4), "osm_class_default", "osm_length_weighted", round(at_["signals"], 2)])
            pts = [roads.nodes[pe[0]["src"]][1:]]
            for e in pe:
                pts += shapes.get((e["src"], e["dst"]), [roads.nodes[e["src"]][1:], roads.nodes[e["dst"]][1:]])[1:]
            wg.writerow([a, b, ";".join(f"{la:.6f} {lo:.6f}" for la, lo in pts)])
    return stations, links, missing, dropped


def build_full(places=None):
    """full: the routing graph is the whole street network (every junction a node, every
    street piece an edge, each direction with its own traffic-light count); stations are
    named junctions on it. Exact for every cost and every condition."""
    roads = ensure_roads(True)
    places = places or load_places()
    shapes, sig = road_pieces(ROADS_ALL_OSM, ROADS_ALL)
    stations, missing, dropped = select_stations("full", roads, places)
    st_at = {s["road_node"]: s for s in stations}
    jid, k = {}, 0
    for n in roads.nodes:
        if n in st_at:
            jid[n] = st_at[n]["id"]
        else:
            k += 1
            jid[n] = f"J{k:05d}"
    extra = []
    for n, (nm, la, lo) in roads.nodes.items():
        if n not in st_at:
            extra.append([jid[n], nm if not re.fullmatch(r"N\d+", nm) else "junction", la, lo, "junction", "", ""])
    out = os.path.join(HERE, LEVELS["full"])
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "roads_source.txt"), "w", encoding="utf-8") as f:
        f.write("\n")  # the graph itself is the street network: no separate background
    rows, used, k_split = [], set(), k
    with open(os.path.join(ROADS_ALL, "edges.csv"), encoding="utf-8") as fin:
        for r in csv.DictReader(fin):
            a, b = r["from"], r["to"]
            if a == b:
                continue  # a loop street back to the same junction can never be on a shortest route
            shape, L = shapes[(a, b)], float(r["length_km"])
            if frozenset((a, b)) not in used:
                used.add(frozenset((a, b)))
                rows.append((jid[a], jid[b], r, shape, L, sig.get((a, b), 0), sig.get((b, a), 0)))
                continue
            # a second street between the same two junctions: split it in the middle with an extra
            # junction, so every street piece has its own (from, to) and its own shape
            if len(shape) < 3:
                (la1, lo1), (la2, lo2) = shape[0], shape[-1]
                shape = [shape[0], ((la1 + la2) / 2, (lo1 + lo2) / 2), shape[-1]]
            m = len(shape) // 2
            k_split += 1
            mid = f"J{k_split:05d}"
            extra.append([mid, "junction", round(shape[m][0], 6), round(shape[m][1], 6), "junction", "", ""])
            poly = lambda pts: sum(haversine_km(*p_, *q_) for p_, q_ in zip(pts, pts[1:]))
            s1, s2 = shape[:m + 1], shape[m:]
            scale = L / max(poly(s1) + poly(s2), 1e-9)
            rows.append((jid[a], mid, r, s1, poly(s1) * scale, 0.0, sig.get((b, a), 0)))  # lights where you arrive
            rows.append((mid, jid[b], r, s2, poly(s2) * scale, sig.get((a, b), 0), 0.0))
    write_stations(out, stations, roads, extra)
    links = 0
    with open(os.path.join(out, "edges.csv"), "w", newline="", encoding="utf-8") as f, \
            open(os.path.join(out, "geometry.csv"), "w", newline="", encoding="utf-8") as fg:
        w, wg = csv.writer(f), csv.writer(fg)
        w.writerow(EDGE_COLS); wg.writerow(["from", "to", "points"])
        for x, y, r, shape, L, sig_xy, sig_yx in rows:
            dirs = [(x, y, sig_xy)] if int(r["oneway"]) else [(x, y, sig_xy), (y, x, sig_yx)]
            for u, v, n_l in dirs:  # one row per direction: the light count depends on the direction
                w.writerow([u, v, r["road"], r["speed_limit_kmh"], 1, r["base_congestion"], 0, r["highway"],
                            round(L, 4), r["congestion_source"], r["speed_source"], round(n_l, 2)])
                links += 1
            wg.writerow([x, y, ";".join(f"{la:.6f} {lo:.6f}" for la, lo in shape)])
    n_lm = write_landmarks(out)
    return stations, {"n": links, "junctions": len(roads.nodes), "landmarks": n_lm}, missing, dropped


N_LANDMARKS = 8


def write_landmarks(out, k=N_LANDMARKS):
    """ALT landmarks for A*: k junctions spread around the city edge (farthest-point choice) and,
    for every junction, the FREE-FLOW travel time from and to each landmark (speed limit, no
    congestion, no lights: a lower bound of every real edge time under every condition).
    graph.py uses them for a tighter admissible heuristic."""
    lm_file = os.path.join(out, "landmarks.csv")
    if os.path.exists(lm_file):
        os.remove(lm_file)  # the graph must be loaded without the old table
    g = Graph().load(os.path.join(out, "nodes.csv"), os.path.join(out, "edges.csv"))
    fwd, bwd = defaultdict(list), defaultdict(list)
    for e in g.edges:
        w = e["distance_km"] / e["speed_kmh"] * 60
        fwd[e["src"]].append((e["dst"], w))
        bwd[e["dst"]].append((e["src"], w))

    def sssp(adj, src):
        d, pq = {src: 0.0}, [(0.0, src)]
        while pq:
            x, u = heapq.heappop(pq)
            if x > d[u]:
                continue
            for v, w in adj[u]:
                if x + w < d.get(v, float("inf")):
                    d[v] = x + w
                    heapq.heappush(pq, (x + w, v))
        return d

    ids = list(g.nodes)
    _, la, lo = g.nodes["U01"] if "U01" in g.nodes else g.nodes[ids[0]]
    first = max(ids, key=lambda n: haversine_km(la, lo, g.nodes[n][1], g.nodes[n][2]))  # far from the centre
    marks, near = [first], None
    tables = []
    while True:
        frm, to = sssp(fwd, marks[-1]), sssp(bwd, marks[-1])
        tables.append((frm, to))
        d = {n: min(frm.get(n, float("inf")), to.get(n, float("inf"))) for n in ids}
        near = d if near is None else {n: min(near[n], d[n]) for n in ids}
        if len(marks) == k:
            break
        marks.append(max(ids, key=lambda n: near[n] if near[n] < float("inf") else -1))
    with open(lm_file, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id"] + [f"from_{m}" for m in marks] + [f"to_{m}" for m in marks])
        for n in ids:
            w.writerow([n] + [round(frm[n], 5) for frm, _ in tables] + [round(to[n], 5) for _, to in tables])
    return marks


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
    import argparse
    ap = argparse.ArgumentParser(description="Build the UB station graphs from OSM data")
    ap.add_argument("--level", choices=list(LEVELS) + ["all"], default="all",
                    help="small = 53 landmarks (data_ub), medium = + named places (data_ub_m), "
                         "large = + bus stops (data_ub_l), full = every street junction + all stations (data_ub_full)")
    a = ap.parse_args()
    places, roads, pieces = load_places(), None, None
    for level in (LEVELS if a.level == "all" else [a.level]):
        if level == "full":
            if not (os.path.exists(ROADS_ALL_OSM) or os.path.isdir(TILES)) or not os.path.exists(PLACES_MORE):
                print("[full] skipped: run fetch_osm_ub.sh first (street tiles + ub_places_more.json)")
                continue
            stations, info, missing, dropped = build_full(places)
            kinds = defaultdict(int)
            for s in stations:
                kinds[s["kind"]] += 1
            print(f"[full] {LEVELS['full']}/: {len(stations)} stations on {info['junctions']} street junctions, "
                  f"{info['n']} directed street pieces, ALT landmarks {info['landmarks']}; stations by kind: "
                  + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])))
            continue
        if roads is None:
            roads, pieces = ensure_roads(False), road_pieces()
        stations, links, missing, dropped = build(level, roads, places, pieces)
        print(f"[{level}] {LEVELS[level]}/: {len(stations)} stations, {len(links)} directed links "
              f"(landmarks {sum(s['prefix'] == 'U' for s in stations)}, places {sum(s['prefix'] == 'P' for s in stations)}, "
              f"bus stops {sum(s['prefix'] == 'B' for s in stations)}); not found: {missing or 'none'}; "
              f"dropped {len(dropped)}")
        if level == "small":
            print("   dropped:", dropped)


if __name__ == "__main__":
    main()
