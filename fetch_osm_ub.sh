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
# named bus stops (for the "large" station level of make_ub_graph.py)
STOPS="[out:json][timeout:120];(node[\"highway\"=\"bus_stop\"][\"name\"]($B);node[\"public_transport\"=\"platform\"][\"name\"]($B););out body;"
get "$STOPS" data_osm_raw/ub_stops.json '"elements"'
# full level: every street (residential too), in 4 tiles so each request is small enough for the
# busy public server; make_ub_graph.py merges them into data_osm_raw/ub_wide_all.osm
MORE="[out:json][timeout:150];(nwr[\"amenity\"~\"^(school|college|kindergarten|fuel|cinema|library|police|fire_station|post_office|embassy|community_centre)\$\"][\"name\"]($B);nwr[\"tourism\"=\"hotel\"][\"name\"]($B);nwr[\"shop\"=\"supermarket\"][\"name\"]($B);nwr[\"leisure\"~\"^(park|sports_centre)\$\"][\"name\"]($B););out center tags;"
get "$MORE" data_osm_raw/ub_places_more.json '"elements"'
mkdir -p data_osm_raw/tiles
for t in "47.80,106.65,47.90,106.90" "47.80,106.90,47.90,107.15" "47.90,106.65,48.00,106.90" "47.90,106.90,48.00,107.15"; do
  Q="[out:xml][timeout:240];(way[\"highway\"~\"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|living_street)(_link)?\$\"]($t););(._;>;);out body;"
  get "$Q" "data_osm_raw/tiles/streets_$(echo $t | tr ',' '_').osm" '</osm>'
done
rm -f data_osm_raw/ub_wide_all.osm   # rebuilt from the tiles by make_ub_graph.py
