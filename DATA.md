# Dataset notes

## What the current dataset is (nodes.csv, edges.csv)
| Field | Source | Quality |
| --- | --- | --- |
| Node coordinates | Written from memory by the assistant, never checked against a map | Approximate, unverified |
| Which nodes are connected, road names | Assumed layout of central Ulaanbaatar | Not from a map |
| Speed limits, one-way flags | Assumed | Not from a map |
| Road length | Straight-line distance x 1.3 | Estimated |
| Congestion (base_congestion) | Invented | Synthetic |

Use it only as a demo/model graph. Say so on the slides.

## Upgrading to real map data (OpenStreetMap)
1. Download the map on your own computer (the workspace has no access to OSM):
   openstreetmap.org -> Export, or the Overpass query inside `osm_to_graph.py`.
2. `python3 osm_to_graph.py map.osm --out data_osm --min-class tertiary`
3. `python3 audit.py data_osm` (target: no FAIL, ideally no WARN except congestion)
4. `python3 app.py --data data_osm --list`, then run `traffic.py`, `experiments.py` on it
   (experiments.py and traffic.py load ./nodes.csv + ./edges.csv; copy the files from
   data_osm over them, or ask for a `--data` option there too).

After step 2 the map supplies: geometry, real road length, names, road class, one-way,
maxspeed where tagged. Still assumed: speed for untagged roads (class default) and
congestion (class default, column `congestion_source` = assumed_by_class).

## Real congestion data (the remaining gap)
Ideas that need no paid API: count vehicles from a few public camera images, use a
Google Maps / Yandex typical-traffic screenshot by hour and read the colour per road,
or time a few real trips and calibrate the table in traffic.py. Put measured values in
`base_congestion` and set `congestion_source` to `measured`; audit.py then reports PASS.

## Quality checks (audit.py)
Referential integrity, duplicates, self-loops, bounding box, length vs straight line,
speed range, congestion range, strong connectivity, alternative routes (cycles),
dead ends, and whether lengths / congestion / road class are measured or assumed.
Current dataset: 9 of 12 pass. The 3 warnings are estimated lengths, synthetic
congestion and missing road class.

## Real map data in this project (Week XV)
`data_osm_raw/ub_tertiary.osm` was downloaded once (2026-11-25) from the public
Overpass API (overpass-api.de) with the query in `osm_to_graph.py`, limited to
trunk/primary/secondary/tertiary roads in (47.85,106.75,47.98,107.05).
Data © OpenStreetMap contributors, licence ODbL; keep this attribution when sharing.
`python3 osm_to_graph.py data_osm_raw/ub_tertiary.osm --out data_osm --min-class tertiary`
gives `data_osm/` (1852 nodes, 2444 segments, 3518 directed edges). Everything after the
download runs offline. Audit: 12/13 PASS (the WARN is synthetic congestion).
Use it with `--data data_osm` (app.py, calibrate.py) or `experiments_week15.py`.
Note: `python3 audit.py data_osm` overwrites `audit_report.md` (the city report); restore it afterwards.
