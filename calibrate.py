"""calibrate.py - Week XV: fit the road-class sensitivities k from measured trips.

The Bayesian network gives P(congestion | weather, time); the road-class model
says how strongly each class of road reacts (ROAD_CLASS_K in traffic.py, so far
an assumption). Given a few REAL trips with measured travel times, this script
finds the k values that predict those times best (grid search, RMSE).

Trip file (CSV, one measured trip per row):
    from,to,weather,time,observed_min[,note]
    N01,N15,snow,morning_peak,33.5,phone stopwatch 2026-12-02 08:10
weather: clear|snow|rain   time: off_peak|morning_peak|evening_peak (or "morning peak")
The prediction for a trip is the fastest route time on the conditioned graph
(drivers are assumed to take a good route).

    python3 calibrate.py trips.csv              # fit k on your measured trips
    python3 calibrate.py trips.csv --save results/calibration.json
    python3 calibrate.py --demo                 # SYNTHETIC check: can it recover known k,
                                                # and how many trips are needed?
    python3 app.py ... --k-file results/calibration.json   # use the fitted k

Standard library only, offline.
"""
import argparse
import csv
import itertools
import json
import math
import os
import random

from graph import Graph
from search import astar
from traffic import ROAD_CLASS_K, TIME, WEATHER, apply_conditions, normalize

GRID = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5]
CLASSES = ["local", "main", "arterial"]


def read_trips(path):
    trips = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            trips.append(dict(src=r["from"].strip(), dst=r["to"].strip(),
                              weather=normalize(r["weather"], WEATHER), time=normalize(r["time"], TIME),
                              observed=float(r["observed_min"]), note=r.get("note", "")))
    return trips


def write_trips(path, trips):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["from", "to", "weather", "time", "observed_min", "note"])
        for t in trips:
            w.writerow([t["src"], t["dst"], t["weather"], t["time"], t["observed"], t["note"]])


def predict(g, trips, k, cache=None):
    """Fastest-route time for every trip under the road-class model with sensitivities k."""
    cache = {} if cache is None else cache
    out = []
    for t in trips:
        key = (tuple(k[c] for c in CLASSES), t["weather"], t["time"])
        if key not in cache:
            cache[key] = apply_conditions(g, t["weather"], t["time"], k=k)
        out.append(astar(cache[key], t["src"], t["dst"])[1])
    return out


def errors(pred, trips):
    d = [p - t["observed"] for p, t in zip(pred, trips)]
    return dict(rmse=math.sqrt(sum(x * x for x in d) / len(d)), mae=sum(abs(x) for x in d) / len(d),
                bias=sum(d) / len(d))


def fit(g, trips, grid=GRID):
    """Grid search over k_local x k_main x k_arterial (10^3 = 1000 candidates)."""
    for t in trips:
        if t["src"] not in g.nodes or t["dst"] not in g.nodes:
            raise ValueError(f"unknown node in trip {t['src']} -> {t['dst']}")
    cache, best = {}, None
    for kl, km, ka in itertools.product(grid, repeat=3):
        k = {"local": kl, "main": km, "arterial": ka}
        e = errors(predict(g, trips, k, cache), trips)
        if best is None or e["rmse"] < best[1]["rmse"] - 1e-12:
            best = (k, e)
        cache.clear()  # graphs of one k are not reused by the next k
    return best


def report(g, trips):
    """Fit + compare with: Week XIII uniform model (k = 1) and Week XIV guess."""
    k, e = fit(g, trips)
    rows = [("fitted", k, e)]
    for name, kk in [("uniform (XIII)", {c: 1.0 for c in CLASSES}), ("guess (XIV)", dict(ROAD_CLASS_K))]:
        rows.append((name, kk, errors(predict(g, trips, kk), trips)))
    return rows


def make_synthetic_trips(g, true_k, n=60, noise=0.05, seed=15):
    """SYNTHETIC trips for testing the calibration only: the 'observed' time is
    the model time under true_k times (1 + N(0, noise)). Not real data."""
    rng = random.Random(seed)
    ids = list(g.nodes)
    trips = []
    while len(trips) < n:
        s, d = rng.sample(ids, 2)
        w, tm = rng.choice(WEATHER), rng.choice(TIME)
        trips.append(dict(src=s, dst=d, weather=w, time=tm, observed=0.0, note="SYNTHETIC"))
    for t, p in zip(trips, predict(g, trips, true_k)):
        t["observed"] = round(p * (1 + rng.gauss(0, noise)), 2)
    return trips


TRUE_K = {"local": 1.75, "main": 1.0, "arterial": 0.5}   # used only to make synthetic trips


def recovery_study(g, sizes=(30, 60, 120, 240), seeds=(1, 2, 3), noise=0.05):
    """SYNTHETIC: fit k on trips generated from TRUE_K with `noise` relative error;
    report how close the fitted k is, per number of trips (mean over seeds)."""
    rows = []
    for n in sizes:
        errs, exact = [], 0
        for sd in seeds:
            k, _ = fit(g, make_synthetic_trips(g, TRUE_K, n=n, noise=noise, seed=sd))
            errs.append({c: abs(k[c] - TRUE_K[c]) for c in CLASSES})
            exact += all(k[c] == TRUE_K[c] for c in CLASSES)
        rows.append(dict(trips=n, noise_pct=round(100 * noise), runs=len(seeds), exact_recoveries=exact,
                         **{f"mean_abs_err_{c}": round(sum(e[c] for e in errs) / len(errs), 3) for c in CLASSES}))
    return rows


def print_rows(rows, n):
    print(f"{'model':16}{'k local':>8}{'k main':>8}{'k art.':>8}{'RMSE':>8}{'MAE':>8}{'bias':>8}   ({n} trips, minutes)")
    for name, k, e in rows:
        print(f"{name:16}{k['local']:8.2f}{k['main']:8.2f}{k['arterial']:8.2f}{e['rmse']:8.2f}{e['mae']:8.2f}{e['bias']:+8.2f}")


def main():
    ap = argparse.ArgumentParser(description="Fit road-class sensitivities k from measured trips")
    ap.add_argument("trips", nargs="?", help="CSV: from,to,weather,time,observed_min[,note]")
    ap.add_argument("--data", default=".", help="folder with nodes.csv + edges.csv")
    ap.add_argument("--save", help="write the fitted k as JSON (for app.py --k-file)")
    ap.add_argument("--demo", action="store_true", help="synthetic parameter-recovery check")
    a = ap.parse_args()
    g = Graph().load(f"{a.data}/nodes.csv", f"{a.data}/edges.csv")
    if a.demo:
        study = recovery_study(g)
        os.makedirs("results", exist_ok=True)
        with open("results/calibration_recovery.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(study[0]))
            w.writeheader(); w.writerows(study)
        print(f"SYNTHETIC recovery study (not real data): true k = {TRUE_K}, 5% noise, 3 seeds")
        print(f"{'trips':>6}{'exact':>8}{'|err| local':>13}{'|err| main':>12}{'|err| art.':>12}")
        for r in study:
            print(f"{r['trips']:>6}{str(r['exact_recoveries']) + '/' + str(r['runs']):>8}{r['mean_abs_err_local']:>13.3f}"
                  f"{r['mean_abs_err_main']:>12.3f}{r['mean_abs_err_arterial']:>12.3f}")
        trips = make_synthetic_trips(g, TRUE_K)
        write_trips("results/trips_synthetic.csv", trips)
        print(f"\nOne run in detail: {len(trips)} SYNTHETIC trips (results/trips_synthetic.csv)")
    elif a.trips:
        trips = read_trips(a.trips)
    else:
        ap.error("give a trips CSV or --demo")
    rows = report(g, trips)
    print_rows(rows, len(trips))
    if a.save:
        os.makedirs(os.path.dirname(a.save) or ".", exist_ok=True)
        json.dump({"k": rows[0][1], "rmse_min": round(rows[0][2]["rmse"], 3), "trips": len(trips),
                   "source": "synthetic" if a.demo else a.trips}, open(a.save, "w"), indent=1)
        print(f"saved {a.save}")
    return rows


if __name__ == "__main__":
    main()
