#!/bin/sh
# fetch_osm_ub.sh - the ONLY step that uses the network (run by hand, once).
# Downloads public OpenStreetMap data (ODbL) for the UB station graph:
#   data_osm_raw/ub_places.json       named places (stations are picked from these)
#   data_osm_raw/ub_wide_tertiary.osm trunk..tertiary roads, a bit wider than ub_tertiary.osm
# Then: python3 make_ub_graph.py  (offline)
cd "$(dirname "$0")"
B="47.80,106.65,48.00,107.15"
PLACES="[out:json][timeout:150];(node[\"place\"~\"^(suburb|neighbourhood|quarter|square|locality)$\"]($B);nwr[\"place\"=\"square\"]($B);nwr[\"railway\"=\"station\"][\"name\"]($B);nwr[\"amenity\"~\"^(university|hospital|marketplace|bus_station|theatre)$\"][\"name\"]($B);nwr[\"shop\"=\"mall\"][\"name\"]($B);nwr[\"tourism\"~\"^(attraction|museum|zoo)$\"][\"name\"]($B);nwr[\"leisure\"~\"^(stadium|park)$\"][\"name\"]($B);nwr[\"aeroway\"=\"aerodrome\"]($B);nwr[\"historic\"][\"name\"]($B);nwr[\"amenity\"=\"place_of_worship\"][\"name\"]($B););out center tags;"
ROADS="[out:xml][timeout:180];(way[\"highway\"~\"^(motorway|trunk|primary|secondary|tertiary)(_link)?\$\"]($B););(._;>;);out body;"
get() { # $1 query  $2 out file  $3 check pattern
  for url in https://overpass-api.de/api/interpreter https://overpass.kumi.systems/api/interpreter https://overpass-api.de/api/interpreter https://overpass.private.coffee/api/interpreter; do
    curl -sS --max-time 240 -o "$2" -A "route-search-student-project" --data-urlencode "data=$1" "$url"
    if grep -q "$3" "$2" 2>/dev/null; then echo "ok $2 from $url ($(stat -c %s "$2") bytes)"; return 0; fi
    echo "retry ($url failed)"; sleep 30
  done
  echo "FAILED $2"; return 1
}
get "$PLACES" data_osm_raw/ub_places.json '"elements"'
get "$ROADS" data_osm_raw/ub_wide_tertiary.osm '<way'
