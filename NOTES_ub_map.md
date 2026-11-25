# Accurate Ulaanbaatar map: 53 real stations (`data_ub/`)

The original city graph (`nodes.csv` / `edges.csv`, 15 places) had coordinates written from memory and lengths estimated as straight line × 1.3. `data_ub/` is built from real OpenStreetMap data instead.

The original graph is **unchanged**: the Week XII–XV tests, hand calculations and PDFs depend on its exact numbers.

## How it was built

```sh
sh fetch_osm_ub.sh        # ONLY network step, run once: named places + roads from Overpass (OSM, ODbL)
python3 make_ub_graph.py  # offline: data_osm_wide/ (road network) -> data_ub/
python3 test_ub_graph.py  # 7 checks (also in run_tests.py / pytest)
```

1. **Stations are found by name in OpenStreetMap.** Each name in `make_ub_graph.STATION_SPEC` is looked up in `data_osm_raw/ub_places.json`, so the coordinates come from the map, not from memory. `stations.csv` keeps the OSM feature id (`node/…`, `way/…`) as provenance.
2. **Each station is snapped to the road junction that serves it** (within 800 m; 1.5 km for large areas, i.e. the airport field and the National Park). The node sits on that junction, and the real place is kept as `place_lat` / `place_lon`. The visualizer draws a dotted line from junction to place.
3. **Links follow real roads.** Each station is joined to its 5 nearest stations by the shortest real road path (Dijkstra on 1986 junctions / 2609 road pieces).
   - A path that passes another station is dropped, because it is really A→C→B.
   - Each direction is a separate row, so one-way streets are respected.
4. **Each link records the real road.** Real length, road names, OSM class (trunk / primary / …) and a speed limit / base congestion are chosen so the link's time equals the sum of the real road pieces.
5. **Street shapes:** `geometry.csv` stores the full road shape of every link (on average 86 OSM shape points per link), so the map shows the real streets. The visualizer also draws the whole OSM road network faintly underneath.

Result: **53 stations, 238 directed road links.** Sukhbaatar Square → Buyant-Ukhaa Airport is 15.8 km by road.

## Stations

- **district** (13): Yarmag (U41), Nisekh (U42), Bayankhoshuu (U43), Dambadarjaa (U44), Sharkhad (U45), Ulaankhuaran (U46), Dari-Ekh (U47), 1st Microdistrict (U48), Orbit (U49), Biokombinat (U50), Uliastai (U51), Tsaiz (U52), Zuun Salaa (U53)
- **market** (8): Narantuul Market (U18), Kharkhorin Market (U19), Bayangol Market (U20), Amgalan Market (U21), Khuchit Shonkhor Market (U22), Bars Trade Center (U23), Ogooj Market (U24), Belkh Market (U25)
- **museum** (5): Choijin Lama Temple (U03), National Museum (U04), Bogd Khan Palace (U12), Natural History Museum (U14), Zhukov Museum (U16)
- **mall** (5): Metro Mall (U26), Millennium Mall (U27), Home Plaza (U28), Max Mall (U29), Bombogor Center (U30)
- **bus terminal** (4): Dragon Bus Terminal (U34), Bayanzurkh Bus Terminal (U35), Lavai Bus Terminal (U36), Dunjingarav (U37)
- **university** (3): Arts and Culture University (U07), Medical Sciences University (U08), Railway University (U09)
- **square** (2): Sukhbaatar Square (U01), Officers' Roundabout (U17)
- **monastery** (2): Gandan Monastery (U02), Dashchoilin Monastery (U06)
- **stadium** (2): Central Stadium (U11), Buyant-Ukhaa Sports Complex (U40)
- **station** (2): Ulaanbaatar Railway Station (U31), Tolgoit Station (U32)
- **hospital** (2): Trauma Hospital (U38), Khan-Uul Hospital (U39)
- **theatre** (1): Drama Theatre (U05)
- **bridge** (1): Peace Bridge (U10)
- **memorial** (1): Zaisan Memorial (U13)
- **park** (1): National Park (U15)
- **airport** (1): Buyant-Ukhaa Airport (U33)

## How wrong the old 15-node graph was

Distance between the old (from memory) position and the real OSM position of the same place:

| Old node | Real place | Error |
| --- | --- | --- |
| Sukhbaatar Square | Sukhbaatar Square | 24 m |
| Buyant-Ukhaa | Buyant-Ukhaa Airport | 22 m |
| Gandan | Gandan Monastery | 204 m |
| Railway Station | Ulaanbaatar Railway Station | 400 m |
| Peace Bridge | Peace Bridge | 717 m |
| Yarmag | Yarmag | 838 m |
| Zaisan | Zaisan Memorial | 897 m |
| Narantuul | Narantuul Market | **3.9 km** |
| Tolgoit | Tolgoit Station | **4.5 km** |

## Using it

```sh
python3 visualizer.py                                       # opens on this map (default now)
python3 visualizer.py --weather snow --time evening peak --road-class
python3 app.py --data data_ub --list                        # station ids
python3 app.py --data data_ub --from U01 --to U33 --compare --weather snow --time evening peak --road-class
```

Real output of the last command: Sukhbaatar Square → Drama Theatre → Bogd Khan Palace → Khan-Uul Hospital → Lavai Bus Terminal → Yarmag → Buyant-Ukhaa Sports Complex → Buyant-Ukhaa Airport. That is 26.55 min (UCS and A* agree; A* expanded 40 nodes vs 51). The route follows Chinggis Avenue south over Peace Bridge, then Naadamchdyn Road west, which is how you actually drive to the old airport.

## Tests (`test_ub_graph.py`, all pass)

1. 53 stations, unique names, all inside UB.
2. Place coordinates equal the OSM features (re-checked from the raw file, max difference 0.06 m). Each node is its serving junction, and snap distances are within limits.
3. Every link has its full street shape, starting and ending at its stations, with length within 3% of the road length and never shorter than the straight line.
4. Every station reaches every other.
5. UCS == A* on all 2756 pairs × time/dist × 4 settings (plain, clear off-peak, snow evening with road class, rain morning with E[t]). The heuristic is consistent on every link.
6. Geography sanity: Zaisan is south of the square, Narantuul east, the airport south-west, the railway station west, Dambadarjaa north. Square → airport is 15.8 km by road.
7. `app.py --data data_ub` works.

`test_visualizer.py` also draws every view on this map. The visualizer window was checked on screen: map, route details, step-by-step and clicking on the map.

## Assumptions and limits

- **Missing stations.** 56 places were requested. Not included:
  - Astronomical Observatory: 2.6 km from a tertiary-or-bigger road.
  - Chingeltei district: 1.6 km away, a ger area with only small roads.
  - Amgalan Station: same junction as Amgalan Market.
  - Peace Bridge is a road, not a place, so its position is the middle of the OSM road named "Peace Bridge".
- **Only trunk to tertiary roads are used**, not residential streets. Small streets inside districts are missing, so a few places snap to a junction up to 0.7 km away (1.3 km for the National Park area). The snap distance of every station is in `stations.csv`.
- **Congestion is still assumed**, from OSM class defaults (`osm_to_graph.py`). Lengths, road classes, one-way rules, names and positions are real.
- **Station ids U01…U53** are assigned in list order. Rebuilding with a different list changes them.
- **New Ulaanbaatar International Airport (Khushig Valley) is outside this area**, about 50 km south. "Buyant-Ukhaa Airport" is the old city airport (OSM name).
