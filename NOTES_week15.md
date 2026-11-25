# Week XV notes: real OSM graph, expected travel time, calibration

Week XV follows the "next steps" slide of `progress_week14.pdf`:
- All experiments on an OpenStreetMap graph.
- Calibrating the CPD / k with measured trips.
- Testing E[t] instead of t(E[c]).

The final report and presentation are left for Week XVI.

## What was added / changed

| File | Status | What |
| --- | --- | --- |
| `data_osm_raw/ub_tertiary.osm` | new (downloaded once) | OSM export of Ulaanbaatar, trunk to tertiary roads. © OpenStreetMap contributors, ODbL |
| `data_osm/` | generated | `osm_to_graph.py` output: 1852 nodes, 3518 directed edges, ≈533 km of road |
| `graph.py` | safety fix | The heuristic speed is the fastest road in the graph (never below 70 km/h). For measured `length_km`, the length is at least the straight line and times round **up**. No change on the city or 64-node graphs |
| `traffic.py` | extended | `expected="time"` (E[t]), `k=` override, road class from the OSM `highway` tag |
| `calibrate.py` | new | Fits k from measured trips (grid search, RMSE). `--demo` runs a synthetic recovery study. `--save` writes JSON for `app.py --k-file` |
| `experiments_week15.py` | new | E1 UCS vs A* on OSM; E2 route changes on OSM; E3 E[t] vs t(E[c]) on 3 graphs |
| `app.py` | extended | `--expected-time`, `--k-file FILE`, `--roads`. Default output still equals Week XII |
| `test_week15.py` | new | 14 checks |
| `run_tests.py` | 1 line | Also runs `test_week15.py` |
| `make_progress_week15.py` | new | Runs E1–E3, the calibration study and the OSM demo, then builds `UBT_progress_week15.pptx` and `progress_week15.pdf` |
| `DATA.md` | appended | Where the OSM data comes from and how it was built |

New dev dependency: `defusedxml` (safe XML parsing in `osm_to_graph.py`; pip, pyenv 3.11). The route-search code still uses the standard library only.

## Commands

```sh
cd /home/piikee/delen
python3 -m pytest -v                  # 5 passed
python3 run_tests.py                  # 5/5 suites passed (no pytest needed)
python3 experiments_week15.py         # E1-E3 -> results/week15_*.csv (~20 s)
python3 calibrate.py --demo           # synthetic recovery study (~50 s)
python3 calibrate.py my_trips.csv --save results/calibration.json   # with REAL trips
python3 make_progress_week15.py       # everything above + progress_week15.pdf (~70 s)

# demo on the real map (same trip, clear vs snow)
python3 app.py --data data_osm --from N0674 --to N1275 --weather clear --time off-peak --road-class --roads
python3 app.py --data data_osm --from N0674 --to N1275 --weather snow --time evening peak --road-class --roads
# expected travel time on the city graph
python3 app.py --from N01 --to N15 --weather snow --time evening peak --road-class --expected-time
```

Real demo output (2026-11-25, `Route :` line omitted, it lists 40+ stops):

```
[Bayes] weather=clear, time=off_peak -> ... | road-class model
[ASTAR] Ноолуурын гудамж -> Olympic Street / Peace Avenue (optimize: time)
  Roads : Ноолуурын гудамж -> Yйлдвэрийн гудамж -> Dund River Street -> Engels street -> Нарны гүүр -> Undsen khuuliin street -> Seoul Street -> Сөүлийн гудамж -> Chinggis Avenue -> Peace Avenue (43 stops)
  Cost  : 6.25 min | expanded 263 nodes | 0.49 ms
[Bayes] weather=snow, time=evening_peak -> ... | road-class model
[ASTAR] Ноолуурын гудамж -> Olympic Street / Peace Avenue (optimize: time)
  Roads : Ноолуурын гудамж -> Чингисийн өргөн чөлөө -> Chinggis Avenue -> Peace Bridge -> ... -> Peace Avenue (40 stops)
  Cost  : 7.61 min | expanded 210 nodes | 0.43 ms
```

In snow, the clear-weather route would take 8.73 min, so re-routing saves 12.8%. City graph: E[t] = 30.76 min vs t(E[c]) = 30.49 min for N01→N15 (snow, evening, road class).

## Results

**E1. UCS vs A\* on the OSM graph** (500 random ordered pairs, seed 15; Week XII method):

| Condition | Time UCS / A* | Dist UCS / A* | Reduction time / dist | Optimal |
| --- | --- | --- | --- | --- |
| default | 924.4 / 586.8 | 924.1 / 263.6 | **−36.5% / −71.5%** | 1000/1000 |
| clear + off-peak | 924.5 / 547.6 | same | −40.8% / −71.5% | 1000/1000 |
| snow + evening peak | 924.5 / 639.0 | same | −30.9% / −71.5% | 1000/1000 |

All 5000 searches agree (500 pairs × 5 conditions × time/dist). The reduction grows with graph size: −17%/−34% on 15 nodes, −29%/−58% on 64 nodes, and −37%/−72% on 1852 nodes. In ms, A* and UCS are about equal (~1 ms), because the heuristic costs extra work on every expansion.

**E2. Routes changed vs clear + off-peak, OSM** (500 pairs):

| Model | rain + morning | snow + morning | snow + evening | Max saved |
| --- | --- | --- | --- | --- |
| uniform (XIII) | 10.2% | 13.2% | 16.6% | 3.6% |
| road class from OSM tag (XIV/XV) | 33.4% | 39.4% | **40.8%** | **13.0%** |

**E3. E[t] vs t(E[c])** (road-class model): E[t] is on average 1.9–4.6% higher (max 11.7%). It picks a different route for 0% (city), up to 8.4% (64 nodes) and up to 10.2% (OSM) of pairs. UCS == A* everywhere.

**Calibration** (`results/calibration_recovery.csv`; SYNTHETIC trips made from k = 1.75/1.0/0.5 with 5% noise, 3 seeds):

| Trips | Mean abs error: k local | k main | k arterial |
| --- | --- | --- | --- |
| 30 | 0.25 | 0.17 | 0.08 |
| 60 | 0.33 | 0.08 | 0.08 |
| 120 | 0.42 | 0.00 | 0.08 |
| 240 | 0.08 | 0.08 | 0.00 |

- With no noise, the fit recovers k exactly (tested).
- k_main and k_arterial are well determined by about 60 trips.
- k_local is weakly identifiable. Central streets already sit near the 0.95 congestion cap in bad conditions, so a larger k changes trip times very little. It needs on the order of 240 trips.

## Assumptions and decisions

1. **The OSM download was a one-time network call.** The project still runs offline. Overpass was overloaded and two mirrors timed out; the main server answered on a later retry. The query used is the one already written in `osm_to_graph.py`, limited to tertiary roads and above (residential roads would make the graph ~10× larger).
2. **`graph.py` was changed**, which the Week XIII brief listed as "do not break". The changes keep every earlier output identical (all fixture tests pass), and they are needed for correctness on real data:
   - OSM speed limits above 70 km/h would make the fixed 70 km/h heuristic inadmissible.
   - OSM lengths can equal the straight line, so rounding down could break consistency.
   - Tests check this on a synthetic 110 km/h road and on every OSM edge (min slack 0.0035 min).
3. **Base congestion on OSM is the class default** from `osm_to_graph.py` (assumed). The road class for k comes from the `highway` tag: motorway/trunk are arterial, primary/secondary are main, tertiary and smaller are local.
4. **E1–E3 on OSM use 500 random ordered pairs** (seed 15) instead of all 3.4 million pairs.
5. **The calibration target** is the fastest-route time under the conditions (it assumes drivers take a good route). Grid: k ∈ {0.25, …, 2.5}, 1000 candidates. The Δ and CPD stay fixed; only k is fitted.
6. **`--k-file` implies the road-class model.** `--expected-time`, `--k-file` and `--road-class` without `--weather`/`--time` are usage errors (exit 2).
7. **`--roads` skips unnamed OSM pieces** (shown as `tertiary 12345`). OSM mixes Mongolian and English names for the same street (Chinggis Avenue / Чингисийн өргөн чөлөө), and the list shows them as they are in the data.

## Could not be done / caveats

- **No real trip measurements exist**, so calibration was only checked on synthetic trips. To use it, measure trips (from, to, weather, time, minutes) into a CSV and run `python3 calibrate.py trips.csv --save results/calibration.json`.
- **Congestion on the OSM graph is still assumed** (class defaults), as are the CPDs, Δ and k.
- **The OSM node ids (N0001…) differ from the city graph ids (N01…).** The two graphs are separate data sets.
- **`progress_week15.pdf` takes about 70 s to build**, because it reruns all experiments and the calibration study.

## Visualizer (`visualizer.py`)

```sh
python3 visualizer.py                                   # opens the window
python3 visualizer.py --graph osm --weather snow --time evening peak --road-class
python3 visualizer.py --congestion high --time morning peak   # diagnostic reasoning in the BN tab
python3 visualizer.py --snapshot out_dir                # 6 PNGs, no window
python3 test_visualizer.py                              # 11 headless checks (also in run_tests.py / pytest)
```

Tabs:
- **Map & route:** roads coloured by E[congestion], the UCS/A* routes, and the nodes each search expanded. Left click sets the start, right click the destination. The toolbar zooms and pans.
- **Route details:**
  - The A* route with numbered stops, the time since the start at each stop, and direction arrows.
  - A "how fast it got there" chart (time against distance, with vs without conditions).
  - Minutes and effective speed per road segment.
  - A pipeline strip showing which methods were used (edges.csv → Bayes net → road class k → E[c] or E[t] → UCS / A*).
  - **Click a road or bar** to see its full calculation with the numbers filled in (`viz_trace.explain_edge`), plus the source of every method involved with the key line highlighted. **Click a box** to see that method's code.
- **Step-by-step (code):** UCS and A* run side by side, one step at a time (`viz_trace.trace`, identical to `search.py`, tested on 1680 runs).
  - The maps show expanded nodes (done), the queue (frontier), the road being checked, the current node and the final path.
  - Under each map is the real `search.py` source: the running line is highlighted with ➜ and each line shows how many times it has run.
  - The status shows the current node with g / h / f, the road being relaxed, and the 5 cheapest queue entries.
  - Controls: Play / Step / Next expansion / To the end / Restart / speed. When both finish, it reports e.g. "A* reached the goal in 49 steps (6 expanded), UCS in 68 steps (8 expanded). Same cost: yes".
- **Bayesian network:** prior (outline) vs posterior (filled) for W, T and C. Setting "observed congestion" shows P(W | C) and P(T | C).
- **CPD table:** the 9 rows with Σ = 1 marks, a heatmap of P(high | W, T), the priors, k and Δ.
- **Checks:** exact vs sampling for the current query (predictive or diagnostic), sampling error vs n against a 1/√n line, UCS vs A* on random pairs, and a PASS/FAIL panel.

Notes:
- **tkinter:** the pyenv Python 3.11 has no tkinter, so the window is reopened with `/usr/bin/python3` (3.14, which has tkinter and matplotlib). `--snapshot` works with any Python.
- **Sampling:** evidence on the root nodes W and T is clamped. That equals rejection sampling with equal weights, and it is much faster. Evidence on C uses real rejection sampling.
- **Observed congestion only affects the BN tab.** Routes use P(C | W, T), because `apply_conditions` takes weather and time only.
- **Tests:** a GUI smoke test (19 steps: all controls, tabs, map clicks, three graphs) passed on the real display. `test_visualizer.py` covers the logic headless, including hand case J: P(W | morning peak, C=high) = 0.619 / 0.215 / 0.166.
