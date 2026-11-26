# Accurate Ulaanbaatar map: 4 data levels, exact street routing, traffic lights

The original city graph (`nodes.csv` / `edges.csv`, 15 places) had coordinates written from memory and lengths estimated as straight line × 1.3. It is **unchanged**, because the Week XII–XV tests, hand calculations and PDFs depend on its exact numbers. The Week XV OSM graph (`data_osm/`) is unchanged too.

All new data is real OpenStreetMap data (© OpenStreetMap contributors, ODbL):

| Level | Folder | Stations | Routing graph | What is in it |
| --- | --- | --- | --- | --- |
| small | `data_ub/` | 53 | 53 nodes, 495 links | landmarks (U01–U53) |
| medium | `data_ub_m/` | 130 | 130 nodes, 1069 links | + 77 named places (P…): markets, malls, universities, hospitals, museums, theatres, temples, districts |
| large | `data_ub_l/` | 257 | 257 nodes, 1432 links | + 127 named bus stops (B…) |
| **full** | `data_ub_full/` | **535** | **25 810 street junctions, 62 128 directed street pieces** | every street incl. residential; stations = 56 landmarks + named places + **216 bus stops** + schools (53), kindergartens, hotels, petrol stations, police, fire stations, libraries, … |

Landmarks have the same id, name **and serving junction** on every level (tested), so `--from U01 --to U33` means the same trip everywhere. On the full level, three more landmarks fit, because a street now reaches them: Astronomical Observatory (U54), Amgalan Station (U55), Chingeltei (U56).

## Why a full level: exact routing

On small / medium / large, a link between two stations is **one fixed road path** with one averaged speed, congestion and road class. Two consequences:

- **Distance:** within 5% of the real road distance (greedy spanner, tested), but not exact.
- **Conditions:** in snow, local streets slow ×1.5 and bypasses only ×0.5, so the real fastest road between two stations can change. A fixed link can't follow that change, and its single averaged class hides it.

On the **full** level the routing graph *is* the street network. Every street piece gets the congestion / road-class / traffic-light model separately. Routes are therefore exact under every weather / time condition, for time and for distance.

Measured on 36 random landmark pairs × 2 settings (`test_ub_graph.py`):

- The large graph's own route, timed street by street on the full graph, is **never faster** than the full graph's best route (the optimality check).
- The full graph finds routes **4.8% faster on average, up to 22.9%**, mostly through streets the station graph doesn't have.
- The large graph's own time estimate for its route is off by **−2.4% … +2.0%** (the averaging error).
- The full graph's shortest distance is never longer than the station graph's.

## Better calculation

1. **Traffic lights.**
   - OSM marks 117 junction lights (`highway=traffic_signals`) and 244 pedestrian-crossing lights (`crossing=traffic_signals`) on UB's streets.
   - A light counts on the street piece that arrives at it, so once per trip and direction. A pedestrian light counts 0.5, because it has a short cycle and is often green for cars.
   - Expected wait per light: **0.25 × (1 + 2c) min**. That is 15 s in free traffic (uniform delay r²/2C for a 90 s cycle with 45 s red ≈ 11 s, plus ~4 s to stop and start), growing to ~45 s at c = 0.95 as queues build. These are ASSUMED values, like the CPD.
   - Implemented in `graph.py` (`signal_delay_min`, optional `signals` column) and `traffic.py` (`apply_conditions`, E[t]). Data without a `signals` column gives exactly the old times (all fixture tests pass).
   - The wait is ≥ 0, so the A* heuristic stays admissible.
2. **No rounding drift.** Times were rounded up to 0.01 min per edge. On the full graph a route has ~150 pieces, which added ~0.7 min. Data with a `signals` column now keeps 0.0001 min (still rounded **up**, so the heuristic stays consistent). Old data keeps its 0.01 min rounding and numbers.
3. **Landmarks keep their junction.** On the full level the airport (a big area) first snapped to a small street on the far side of the airfield, 1.9 km from its access road. That gave a different, longer trip. Landmarks now keep their small-level junction on every level.
4. **Clean street graph.**
   - Two different streets between the same pair of junctions (30 cases) are split by an extra junction, so each keeps its own exact shape and length.
   - 31 loop streets that return to the same junction are dropped; they can never be on a shortest route.
   - If a street's recorded shape can't be matched (a loop way), it is drawn straight instead of along the wrong part of the loop.
5. **A\* with ALT landmarks** (full level, `landmarks.csv`).
   - 8 junctions around the city edge; for every junction, the free-flow time (speed limit, no congestion, no lights) to and from each one.
   - Triangle inequality: h(n) = max over landmarks L of [d(L,goal) − d(L,n)] and [d(n,L) − d(goal,L)].
   - Every real edge time is ≥ its free-flow time, so h is admissible and consistent under every condition. Tested: consistent on all 62 128 pieces for random goals in snow; UCS == A* on every tested pair.
   - Result on 60 station pairs:

| Search | Junctions expanded vs UCS (default / snow) | Time per search |
| --- | --- | --- |
| UCS | 11 600 / 11 353 | 17–18 ms |
| A* with straight line / 70 km/h | −36% / −31% | 19–21 ms |
| **A* with landmarks** | **−57% / −49%** | 19–23 ms |

In pure Python the extra heuristic work costs about as much as it saves, so wall-clock time stays similar. The search does half the work.

## The same trip on every level (lights included)

`python3 app.py --data <folder> --from U01 --to U33 --compare --weather snow --time evening peak --road-class`

| Level | Time | UCS expanded | A* expanded |
| --- | --- | --- | --- |
| small | 34.40 min | 52 | 45 |
| medium | 33.98 min | 127 | 117 |
| large | 34.54 min | 251 | 212 |
| **full (exact)** | **33.43 min** | 20 347 | 9 051 |

On the full level, `--cost dist` gives 15.31 km. Its fastest route in snow goes Ikh Surguulyn street → Peace Avenue → С.Чоймболын гудамж → Партизаны гудамж → Seoul Street → Undsen khuuliin street → Нарны гүүр → Engels street → Үйлдвэрийн гудамж → Чингисийн өргөн чөлөө → Chinggis Avenue → Наадамчдын зам: about 150 street pieces in 34 ms.

## How it is built

```sh
sh fetch_osm_ub.sh       # ONLY network step, run once (Overpass, OSM): places, main roads, bus stops,
                         # more places, and every street in 4 tiles (one big query times out)
python3 make_ub_graph.py # offline, all 4 levels (~20 s); or --level small|medium|large|full
python3 test_ub_graph.py # 32 checks over the 4 levels (also in run_tests.py / pytest)
```

- **Small / medium / large:** stations (OSM names) are snapped to the main-road junction that serves them. Links come from the greedy spanner: pairs are taken from nearest to farthest, and a real road is added only if the links so far can't do the trip within 5% (tested 1.000 … 1.050). Every link has its real street shape and its traffic lights.
- **Full:**
  - The 4 street tiles are merged into `data_osm_raw/ub_wide_all.osm`, and `osm_to_graph.py --min-class residential` turns it into `data_osm_all/`.
  - Every junction becomes a node. Stations are named junctions; other junctions are `J…` with their street names.
  - Every street piece becomes one row per direction, so its light count is right for that direction. `geometry.csv` stores each street's full shape once.
  - `landmarks.csv` holds the ALT tables.
  - Station spacing is 250 m between places and 150 m between bus stops. Bus stops must be within 150 m of a street.
  - `shop=supermarket` is left out: in UB's OSM data most are small corner shops (506 of them), and big stores are already malls / markets.

## Using it

```sh
python3 visualizer.py --graph ub_full --weather snow --time evening peak --road-class
python3 app.py --data data_ub_full --list                 # the 535 stations (not the 25 000 junctions)
python3 app.py --data data_ub_full --from U01 --to B0012 --weather rain --time morning peak --road-class --roads
```

On the full level:
- `app.py` prints a route as the stations it passes, with "(n junctions)" between them. `--roads` lists the street names.
- **Visualizer:**
  - The map is the street network itself, with residential streets drawn thin. Station names are spaced out; zoom in with the toolbar.
  - Route details groups the ~150 street pieces into ≤ 25 road segments. Clicking a segment explains its slowest piece, including the traffic-light wait.
  - Step-by-step runs on all 25 810 junctions (UCS floods the city; A* with landmarks searches a narrow band).
  - The window opens in ~3 s, and changing the weather re-weights all 62 128 pieces in ~2 s.

## Tests (`test_ub_graph.py`, 32 checks, all pass)

Per level:
1. Size, unique names, inside UB.
2. Every station position equals its OSM feature; the node is its serving junction.
3. Every link / street piece has its full shape, real length (never shorter than the straight line) and its light wait in the time.
4. Strongly connected.
5. UCS == A*, heuristic consistent.
6. **Station levels:** distance within 1.00–1.05 × the real road distance.
7. **Full level:** ALT consistency and gain; exactness vs the large graph.
8. Landmarks identical to the small level.
9. Geography right; `app.py --data …` and `--list` work.

`test_visualizer.py` draws the route and step views on the full graph too. A window test on the full map passed: tabs, segment click, step-by-step to the end, weather change, switching maps.

## Limits

- **Congestion is still assumed** per road class (OSM class defaults), as are the CPD, k and the light-wait numbers. Positions, lengths, road classes, one-way rules, names and traffic lights are real.
- **Not modelled:** turn restrictions and turning delays at junctions without lights.
- **Data size:** the full level is ~15 MB (`data_ub_full/`), plus the raw tiles and their merged copy (~30 MB) in `data_osm_raw/`. If git size matters, the merged file `ub_wide_all.osm` can be left out; `make_ub_graph.py` rebuilds it from the tiles.
- **Ids:** P… and B… ids can change when the data is re-downloaded. U… ids stay stable.
- **Downloads:** `fetch_osm_ub.sh` is the only script that uses the network. Overpass is often overloaded; the script retries and splits the street download into tiles.
