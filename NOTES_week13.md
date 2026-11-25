# Week XIII notes: Bayesian traffic model

## What was added / changed

| File | Status | What |
| --- | --- | --- |
| `traffic.py` | rewritten | Bayesian network Weather × Time → Congestion with explicit CPDs, exact inference, expected congestion per edge, `apply_conditions()`, its own `run_tests()` |
| `app.py` | changed | `--weather clear\|snow\|rain`, `--time off-peak\|morning peak\|evening peak`. The default path is unchanged |
| `test_week13.py` | new | CLI regression (the default output is identical to before), Bayesian CLI, scale graph optimality, offline guard |
| `run_tests.py` | new | Runs every suite: `search.py`, `traffic.py`, `test_week13.py` |
| `scale_test.py` | new | Generates the 64-node graph in `data_scale/` and compares UCS and A* on node expansions |
| `make_progress_week13.py` | new | Builds `UBT_progress_week13.pptx` and `progress_week13.pdf` from the Week XII deck, using numbers from real runs |
| `fixtures/app_output_before_week13.json` | new | `app.py` output recorded **before** any Week XIII change (7 commands, ms masked) |
| `experiments.py` | 1 line | `CONDITIONS` now uses the new time states (it imported the old `night`/`day` names) |
| `data_scale/`, `results/scale_week13.csv` | generated | Scale graph and scale results |
| `progress_week13.pdf`, `UBT_progress_week13.pptx` | generated | 8 slides, same design and length as Week XII |
| `progress_week12.pdf` | generated | Exported from `UBT_progress_week12.pptx` (it was missing) |
| `results/`, `results_before_week13/` | regenerated / backup | Week XIV experiment outputs with the new model; old outputs kept |

`graph.py`, `search.py`, `nodes.csv`, `edges.csv` and `audit.py` were not changed.

## Exact commands (all offline)

```sh
cd /home/piikee/delen

# all tests: search.py (Week XI) + traffic.py (BN, hand calcs, 210 pairs) + test_week13.py
python3 -m pytest -v          # 3 passed (needs pytest: python3 -m pip install -r requirements-dev.txt)
python3 run_tests.py          # same suites without pytest

# demo
python3 app.py --from N01 --to N15 --compare                                      # same as Week XII
python3 app.py --from N01 --to N15 --compare --weather snow --time morning peak   # Bayesian conditions
python3 app.py --from N01 --to N08 --weather rain                                 # time unknown -> summed out
python3 traffic.py --demo                                                         # CPD table + per-edge E[c]

# scale test (64 nodes) and the report
python3 scale_test.py
python3 make_progress_week13.py        # needs LibreOffice (soffice), runs locally
```

Real output of the two main demo commands (2026-11-25):

```
$ python3 app.py --from N01 --to N15 --compare
--- Compare on Sukhbaatar Square -> Buyant-Ukhaa (time) ---
[UCS] Sukhbaatar Square -> Buyant-Ukhaa (optimize: time)
  Route : Sukhbaatar Square -> Zaisan -> Khan-Uul District -> Yarmag -> Buyant-Ukhaa
  Cost  : 27.09 min | expanded 15 nodes | 0.01 ms
[ASTAR] Sukhbaatar Square -> Buyant-Ukhaa (optimize: time)
  Route : Sukhbaatar Square -> Zaisan -> Khan-Uul District -> Yarmag -> Buyant-Ukhaa
  Cost  : 27.09 min | expanded 12 nodes | 0.02 ms
  Same optimal cost: yes | A* expanded 3 fewer nodes

$ python3 app.py --from N01 --to N15 --compare --weather snow --time morning peak
[Bayes] weather=snow, time=morning_peak -> P(congestion low/medium/high) = 0.05 / 0.30 / 0.65, expected level 0.71
--- Compare on Sukhbaatar Square -> Buyant-Ukhaa (time) ---
[UCS] Sukhbaatar Square -> Buyant-Ukhaa (optimize: time)
  Route : Sukhbaatar Square -> Zaisan -> Khan-Uul District -> Yarmag -> Buyant-Ukhaa
  Cost  : 31.44 min | expanded 15 nodes | 0.01 ms
[ASTAR] Sukhbaatar Square -> Buyant-Ukhaa (optimize: time)
  Route : Sukhbaatar Square -> Zaisan -> Khan-Uul District -> Yarmag -> Buyant-Ukhaa
  Cost  : 31.44 min | expanded 12 nodes | 0.02 ms
  Same optimal cost: yes | A* expanded 3 fewer nodes
```

Test result: `python3 -m pytest -v` gives `3 passed` (test_search_suite, test_traffic_suite, test_week13). `python3 run_tests.py` gives `3/3 suites passed` on Python 3.11.15 (pyenv `python3`) and on 3.14.10 (`/usr/bin/python3`).

Scale test (`results/scale_week13.csv`). Week XII method: mean nodes expanded over all ordered pairs i ≠ j, reduction = 1 − mean(A*)/mean(UCS):

| Graph | Condition | Pairs | Time UCS/A* | Dist UCS/A* | Reduction time / dist | Optimal |
| --- | --- | --- | --- | --- | --- | --- |
| city, 15 nodes | default | 210 | 8.50 / 7.02 | 8.50 / 5.60 | −17% / −34% (= Week XII) | 420/420 |
| city, 15 nodes | snow + morning peak | 210 | 8.50 / 7.38 | 8.50 / 5.60 | −13% / −34% | 420/420 |
| scale, 64 nodes | default | 4032 | 33.00 / 23.57 | 33.00 / 13.86 | **−29% / −58%** | 8064/8064 |
| scale, 64 nodes | clear + off-peak | 4032 | 33.00 / 22.16 | 33.00 / 13.86 | −33% / −58% | 8064/8064 |
| scale, 64 nodes | rain + morning peak | 4032 | 33.00 / 24.63 | 33.00 / 13.86 | −25% / −58% | 8064/8064 |
| scale, 64 nodes | snow + morning peak | 4032 | 33.00 / 25.15 | 33.00 / 13.86 | −24% / −58% | 8064/8064 |

(The UCS mean is always (n+2)/2. UCS expands nodes in order of cost until it reaches the goal, so the average over all goals is fixed. Heavier congestion makes the 70 km/h heuristic less tight, so A* saves less in bad conditions.)

## Assumptions and decisions

1. **Model states follow the task spec.** Weather is clear/snow/rain and time is off_peak/morning_peak/evening_peak. An earlier draft of `traffic.py` (from 20 Nov) used 4 time states (night/day/morning/evening). It was replaced, and `experiments.py` was updated to the new names.
2. **All probabilities are synthetic.** There is no measured data. The sources are in comments in `traffic.py`:
   - P(W): Ulaanbaatar is dry. We assume about 30% of days have precipitation, split evenly between snow and rain.
   - P(T): share of the 24 h day. Morning peak 07:30–10:00 (0.10), evening peak 17:00–20:30 (0.15), off-peak the rest (0.75).
   - CPD: expert-style guesses following three rules: peak > off-peak, evening > morning, snow > rain > clear.
3. **How congestion reaches each edge.** The level is city-wide. `base_congestion` in `edges.csv` is read as the road on a "medium" day.
   - A level shifts a road by Δ = −0.25 / 0 / +0.25, clipped to [0, 0.95].
   - Expected congestion per edge: E[c_e] = Σ_l P(l | W, T) · clip(base_e + Δ_l).
   - The edge time uses the existing formula with E[c_e]. This is time at the expected congestion, not the expected time. E[time] would be a bit higher (Jensen), but the task asked for the expected congestion.
4. **Why A* stays optimal.** c ≥ 0 means effective speed ≤ speed limit ≤ 70 km/h, and length ≥ straight line. So every edge costs ≥ straight-line / 70 km/h, which makes h consistent. A test checks this on every edge under 12 conditions (minimum slack 0.85 min). `graph.py` still hard-codes 70 km/h; a future OSM graph with speed limits above 70 would need a larger heuristic speed. The scale graph uses speeds ≤ 70.
5. **Missing evidence.** If only `--weather` or only `--time` is given, the other variable is summed out with its prior. With neither, the BN is not applied at all, so the output stays exactly as in Week XII.
6. **`--time morning peak`** is accepted as two words, as well as `morning_peak`, `morning-peak` and `Off-Peak`. Unknown values give an argparse usage error (exit 2).
7. **Rounding.** `time_min` is rounded to 2 decimals, as `graph.py` already does. Optimality checks compare UCS and A* on the same rounded weights.
8. **"Identical to before"** is checked against `fixtures/app_output_before_week13.json`, recorded from the code before any edit. The `x.xx ms` timing is masked because it changes on every run.
9. **The scale graph** is an 8×8 jittered grid over the UB bounding box (seed 13), 64 nodes and 128 segments (9 one-way, made strongly connected). Speeds are 40–70 km/h. Congestion is synthetic and higher toward the centre. `audit.py data_scale` gives 9/12 PASS with the same 3 WARNs as the city graph.
10. **Tests use the existing style** (`run_tests()` printing `[PASS]/[FAIL]`, with an exit code). pytest 9.2.0 and matplotlib 3.11.2 were installed (with your approval) into pyenv Python 3.11.15, which is the `python3` here. They are listed in `requirements-dev.txt`. They are dev/chart tools only; the route-search code uses the standard library and runs offline.
11. **The 210-pair check** runs on both `time` and `dist` costs, under all 9 weather × time combinations plus snow/any, any/evening and any/any (12 conditions).

## Could not be done / caveats

- **`progress_week12.pdf` was missing** from the folder. It was exported from `UBT_progress_week12.pptx` with LibreOffice (8 pages, contents unchanged). That deck was also the template for `progress_week13.pdf`.
- **The weather rarely changes the route** on the 15-node graph. Conditions shift all roads together, so only travel times change. At most 1/210 routes changed under any single condition (N04→N05 under clear/rain off-peak). This is listed as a risk in the deck. A fix would be road-class-specific CPDs.
- **`results/` was regenerated** with the new model (`python3 experiments.py`). The old 20 Nov outputs (4-state model) are kept in `results_before_week13/`. `summary.csv` and `bayes_check.csv` in the project root are older copies from 20 Nov and were left as they are.
- `audit.py` always writes `audit_report.md`. Running it on `data_scale/` overwrote the city report once. The original was restored, so the file is unchanged.
- The deck's speaker notes for slides 1–6 were updated; slides 7–8 had no notes.
