# Week XIV notes: experiments A–D and the road-class congestion model

Week XIV follows the "next steps" slide of `progress_week13.pdf`:
- `experiments.py`: 30 pairs × 4 conditions × 10 repeats.
- Distance-only route vs traffic-aware route.
- Hand calculation vs Bayesian network vs sampling.
- A different CPD effect per road class.

Week XIII risk: weather almost never changed a route. Experiment D measures that, and the road-class model addresses it.

## What was added / changed

| File | Status | What |
| --- | --- | --- |
| `traffic.py` | extended | `ROAD_CLASS_K`, `road_class()`, and `apply_conditions(..., by_class=False)`. The default is the unchanged Week XIII model |
| `app.py` | extended | `--road-class` (needs `--weather` and/or `--time`). The default output is still the Week XII output |
| `experiments.py` | extended | Experiment D (`route_model_experiment()`), writing `results/route_model.csv` and `results/chart_route_changes.png` |
| `test_week14.py` | new | 11 checks: road-class hand calculations, optimality, CLI, experiments C and D |
| `run_tests.py` | 1 line | Also runs `test_week14.py` |
| `make_progress_week14.py` | new | Runs experiments A–D and the demo, then builds `UBT_progress_week14.pptx` and `progress_week14.pdf` (Week XII design, 8 slides) |
| `results/*` | regenerated | Every run of `make_progress_week14.py` regenerates them, so the PDF and the CSVs always come from the same run |

## Commands (all offline)

```sh
cd /home/piikee/delen
python3 -m pytest -v                 # 4 passed
python3 run_tests.py                 # 4/4 suites passed (no pytest needed)
python3 experiments.py               # A-D, writes results/
python3 make_progress_week14.py      # runs experiments + demo, writes progress_week14.pdf

# demo: same trip, the route moves to the bypass in a snowy evening peak
python3 app.py --from N04 --to N05 --weather clear --time off-peak --road-class
python3 app.py --from N04 --to N05 --weather snow --time evening peak --road-class
```

Real output of the demo (2026-11-25):

```
[Bayes] weather=clear, time=off_peak -> P(congestion low/medium/high) = 0.60 / 0.30 / 0.10, expected level 0.33 | road-class model
[ASTAR] Railway Station -> Zaisan (optimize: time)
  Route : Railway Station -> Ard Cinema -> Peace Bridge -> Zaisan
  Cost  : 9.57 min | ...

[Bayes] weather=snow, time=evening_peak -> P(congestion low/medium/high) = 0.03 / 0.22 / 0.75, expected level 0.75 | road-class model
[ASTAR] Railway Station -> Zaisan (optimize: time)
  Route : Railway Station -> Bayangol -> Khan-Uul District -> Zaisan
  Cost  : 12.57 min | expanded 6 nodes | ...
```

Under snow + evening peak, the old central route would take 14.73 min, so re-routing saves 14.7%. This is hand case H in `test_week14.py`.

## Results (from `results/`; timings in ms change slightly every run)

**A. UCS vs A\*** (15-node city graph; 30 pairs × 4 conditions × 10 repeats = 1200 runs): 1200/1200 have the same optimal cost.

| Condition | UCS nodes | A* nodes | Fewer |
| --- | --- | --- | --- |
| clear + off-peak | 8.00 | 6.10 | −23.8% |
| rain + morning peak | 7.97 | 6.53 | −18.0% |
| snow + morning peak | 7.97 | 6.63 | −16.7% |
| snow + evening peak | 7.97 | 6.67 | −16.3% |

A* expands fewer nodes, but on 15 nodes it is **slower in ms** (about 0.014 vs 0.009 ms), because the haversine heuristic costs more than the work it saves.

**B. Distance-only route vs traffic-aware route** (city graph): the distance route is slower on at most 1/30 pairs. The average loss is 0.2%; the largest is 5.7% (snow + evening peak).

**C. Hand calculation vs BN vs sampling** (6 queries): hand calculation and BN agree to ≤ 1.1e-16. Rejection sampling (1000 × 10) has a mean absolute error of ≤ 0.0182.

**D. Routes changed vs clear + off-peak** (`results/route_model.csv`):

| Graph | Model | rain + morning | snow + morning | snow + evening | Max time saved |
| --- | --- | --- | --- | --- | --- |
| city, 15 nodes | uniform (XIII) | 0.5% | 0.5% | 0.5% | 5.7% |
| city, 15 nodes | road-class (XIV) | 1.9% | 1.9% | 1.9% | 14.7% |
| scale, 64 nodes | uniform (XIII) | 8.5% | 13.9% | 14.4% | 6.5% |
| scale, 64 nodes | road-class (XIV) | 21.7% | 28.7% | **31.9%** | **29.5%** |

UCS and A* agree on every pair in every row of D.

Conclusion: the Bayesian conditions do change routes, but only where alternative routes exist. On the 15-node graph there are few, so the effect is small. On the 64-node graph, 14% of routes change with the uniform model and 32% with the road-class model.

## Assumptions and decisions

1. **Road class comes from the speed limit**, because `edges.csv` has no class column: ≤ 40 km/h is local, 50 km/h is main, ≥ 60 km/h is arterial.
   - The class sensitivity k scales the level shift: local ×1.5, main ×1.0, arterial ×0.5.
   - These numbers are assumptions (reasons are in comments in `traffic.py`).
   - The formula is c_e = clip(base_e + k · Δ_level, 0, 0.95).
2. **The road-class model is opt-in** (`by_class=True`, `--road-class`). All Week XIII numbers, tests and `progress_week13.pdf` stay valid; a test checks that `by_class=False` is identical.
3. **Admissibility is unchanged.** The clip to [0, 0.95] and speeds ≤ 70 km/h keep h consistent; this is tested under 9 conditions (minimum slack 0.85 min). UCS == A* on 210 pairs × 9 conditions × time/dist with the class model, and on all 4032 pairs of the 64-node graph.
4. **What "route changed" means in Experiment D:** the optimal node sequence differs from the clear + off-peak plan. "Time saved" is the time of the old plan on the new weights, minus the new optimum, divided by the old plan's time. It is never negative, which a test checks.
5. **Experiment D uses the generated 64-node graph** (`data_scale/`, made by `scale_test.py` with a fixed seed). If the folder is missing, it is regenerated.
6. **`--road-class` without `--weather`/`--time` is a usage error** (exit 2). Without conditions there is no level to scale.
7. **No Week XV plan exists in the project.** The "next steps" slide proposes one: final report, calibrating the CPD and k with a few measured trips, all experiments on an OSM graph, and testing E[time] instead of time at E[congestion].

## Could not be done / caveats

- **There is still no real traffic data.** The CPDs, Δ and k are assumptions. All experiments compare models with each other, not with reality.
- **The road class is guessed from the speed limit.** With an OSM graph (`osm_to_graph.py`), the `highway` tag could be used instead; this is not implemented.
- **ms timings differ between runs and machines.** The PDF shows the values from the run that built it, and they match `results/summary.csv` from that same run.
- **Each `make_progress_week14.py` run overwrites `results/`.** Week XIII's `results/scale_week13.csv` is written by `scale_test.py` and isn't affected. The 20 Nov outputs are still in `results_before_week13/`.
