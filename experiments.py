"""experiments.py - Week XIV: combined comparison experiments.

Plan (from the slides): 30 start/goal pairs x 4 conditions x 10 repeats.
  Experiment A: UCS vs A*  (cost, optimality, nodes expanded, runtime)
  Experiment B: distance-only route vs traffic-aware route (time lost)
  Experiment C: hand calculation vs Bayesian network vs sampling (probability error)
  Experiment D: uniform vs road-class congestion model, 15- and 64-node graphs
                (how many routes change vs clear+off_peak, time saved by re-routing)

Outputs (folder results/): runs.csv, summary.csv, bayes_check.csv, route_model.csv, 5 PNG charts.
"""
import csv
import os
import random
import statistics as st
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from graph import Graph
from search import ucs, astar
from traffic import (apply_conditions, posterior, joint, CPD_CONG, P_WEATHER,
                     P_TIME, WEATHER, TIME, LEVEL)

SEED = 42
N_PAIRS = 30
REPEATS = 10
CONDITIONS = [("clear", "off_peak"), ("rain", "morning_peak"), ("snow", "morning_peak"), ("snow", "evening_peak")]  # Week XIII time states
OUT = "results"
plt.rcParams["font.family"] = "DejaVu Sans"
C_UCS, C_ASTAR, C_ACC = "#9aa2c0", "#5b52a8", "#e5473e"


def path_time(g, path):
    """Travel time (min) of a given path on graph g."""
    total = 0.0
    for a, b in zip(path, path[1:]):
        total += min(e["time_min"] for e in g.adj[a] if e["dst"] == b)
    return total


def pick_pairs(g):
    rng = random.Random(SEED)
    ids = list(g.nodes)
    allp = [(s, t) for s in ids for t in ids if s != t]
    rng.shuffle(allp)
    out = []
    for s, t in allp:
        if ucs(g, s, t, "time")[0] is not None:
            out.append((s, t))
        if len(out) == N_PAIRS:
            break
    return out


def timed(fn, *a):
    t0 = time.perf_counter()
    r = fn(*a)
    return r, (time.perf_counter() - t0) * 1000


# ------------------------- experiments A + B -------------------------
def run_search_experiments(g, pairs):
    rows = []
    for w, tm in CONDITIONS:
        gc = apply_conditions(g, w, tm)
        for s, t in pairs:
            dpath, _, _ = ucs(gc, s, t, "dist")           # distance-only route
            d_time = path_time(gc, dpath)
            for rep in range(REPEATS):
                (pu, cu, xu), mu = timed(ucs, gc, s, t, "time")
                (pa, ca, xa), ma = timed(astar, gc, s, t, "time")
                rows.append(dict(weather=w, time=tm, src=s, dst=t, rep=rep,
                                 ucs_cost=cu, astar_cost=ca, same=abs(cu - ca) < 1e-9,
                                 ucs_nodes=xu, astar_nodes=xa, ucs_ms=mu, astar_ms=ma,
                                 dist_route_time=d_time, same_route=(pu == dpath)))
    return rows


def summarize(rows):
    out = []
    for w, tm in CONDITIONS:
        r = [x for x in rows if x["weather"] == w and x["time"] == tm]
        first = [x for x in r if x["rep"] == 0]  # one record per pair for cost metrics
        saved = [100 * (x["dist_route_time"] - x["ucs_cost"]) / x["dist_route_time"] for x in first]
        out.append(dict(
            condition=f"{w}+{tm}", runs=len(r),
            optimal_same=f"{sum(x['same'] for x in r)}/{len(r)}",
            ucs_nodes=round(st.mean(x["ucs_nodes"] for x in r), 2),
            astar_nodes=round(st.mean(x["astar_nodes"] for x in r), 2),
            nodes_saved_pct=round(100 * (1 - st.mean(x["astar_nodes"] for x in r) / st.mean(x["ucs_nodes"] for x in r)), 1),
            ucs_ms=round(st.mean(x["ucs_ms"] for x in r), 4),
            astar_ms=round(st.mean(x["astar_ms"] for x in r), 4),
            avg_trip_min=round(st.mean(x["ucs_cost"] for x in first), 1),
            dist_route_avg_min=round(st.mean(x["dist_route_time"] for x in first), 1),
            pairs_where_distance_route_is_slower=sum(1 for x in first if x["dist_route_time"] - x["ucs_cost"] > 1e-9),
            avg_time_saved_pct=round(st.mean(saved), 1),
            max_time_saved_pct=round(max(saved), 1)))
    return out


# ------------------------- experiment C -------------------------
def hand_p_high(weather=None, time_=None):
    """Closed-form P(high | evidence) written straight from the CPD table."""
    num = den = 0.0
    for w in WEATHER:
        for t in TIME:
            if (weather and w != weather) or (time_ and t != time_):
                continue
            pw = P_WEATHER[w] * P_TIME[t]
            num += pw * CPD_CONG[(w, t)][2]
            den += pw
    return num / den


def sample_p_high(weather, time_, n, rng):
    """Rejection sampling estimate of P(high | evidence)."""
    hit = kept = 0
    while kept < n:
        w = rng.choices(WEATHER, [P_WEATHER[x] for x in WEATHER])[0]
        t = rng.choices(TIME, [P_TIME[x] for x in TIME])[0]
        if (weather and w != weather) or (time_ and t != time_):
            continue
        c = rng.choices(LEVEL, CPD_CONG[(w, t)])[0]
        kept += 1
        hit += c == "high"
    return hit / n


def bayes_check():
    rng = random.Random(SEED)
    queries = [(w, tm) for w, tm in CONDITIONS] + [("rain", None), (None, "evening_peak")]
    rows = []
    for w, tm in queries:
        ev = {k: v for k, v in (("weather", w), ("time", tm)) if v}
        bn = posterior("congestion", ev)["high"]
        hand = hand_p_high(w, tm)
        est = [sample_p_high(w, tm, 1000, rng) for _ in range(REPEATS)]
        rows.append(dict(evidence=f"{w or '*'} / {tm or '*'}", hand=round(hand, 4), bayes_net=round(bn, 4),
                         hand_minus_bn=f"{abs(hand - bn):.1e}", sampling_mean=round(st.mean(est), 4),
                         sampling_mean_abs_err=round(st.mean(abs(e - bn) for e in est), 4)))
    return rows


# ------------------------- experiment D -------------------------
D_GRAPHS = [("city", ".", "15"), ("scale", "data_scale", "64")]
D_REFERENCE = ("clear", "off_peak")


def route_model_experiment():
    """For each graph and congestion model, plan every pair under the reference
    (clear + off-peak) and under each condition. A route 'changes' when the
    optimal node sequence differs. 'saved' = time lost if you kept the
    reference route under the new condition (evaluated on the new weights)."""
    import scale_test
    if not os.path.exists("data_scale/edges.csv"):
        scale_test.generate()
    rows = []
    for gname, folder, nn in D_GRAPHS:
        g = Graph().load(f"{folder}/nodes.csv", f"{folder}/edges.csv")
        ids = list(g.nodes)
        pairs = [(s, t) for s in ids for t in ids if s != t]
        for model, by_class in (("uniform", False), ("road_class", True)):
            gref = apply_conditions(g, *D_REFERENCE, by_class=by_class)
            ref = {p: astar(gref, *p, "time")[0] for p in pairs}
            for w, tm in CONDITIONS:
                gc = apply_conditions(g, w, tm, by_class=by_class)
                changed, saved, bad = 0, [], 0
                for s, t in pairs:
                    pa, ca, _ = astar(gc, s, t, "time")
                    _, cu, _ = ucs(gc, s, t, "time")
                    bad += abs(ca - cu) > 1e-9
                    if pa != ref[(s, t)]:
                        changed += 1
                        old = path_time(gc, ref[(s, t)])
                        saved.append(100 * (old - ca) / old)
                rows.append(dict(graph=f"{gname} ({nn} nodes)", model=model, condition=f"{w}+{tm}",
                                 pairs=len(pairs), routes_changed=changed,
                                 routes_changed_pct=round(100 * changed / len(pairs), 1),
                                 avg_saved_pct_on_changed=round(st.mean(saved), 1) if saved else 0.0,
                                 max_saved_pct=round(max(saved), 1) if saved else 0.0,
                                 ucs_eq_astar=f"{len(pairs) - bad}/{len(pairs)}"))
    return rows


# ------------------------- output -------------------------
def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)


def bar_pair(ax, labels, a, b, la, lb, ca, cb, fmt="{:.1f}"):
    x = range(len(labels))
    ax.bar([i - .2 for i in x], a, .4, label=la, color=ca)
    ax.bar([i + .2 for i in x], b, .4, label=lb, color=cb)
    for i in x:
        ax.text(i - .2, a[i], fmt.format(a[i]), ha="center", va="bottom", fontsize=8)
        ax.text(i + .2, b[i], fmt.format(b[i]), ha="center", va="bottom", fontsize=8)
    ax.set_xticks(list(x)); ax.set_xticklabels(labels, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False); ax.legend(frameon=False, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.2))


def charts(summ, bayes):
    labels = [s["condition"].replace("+", "\n") for s in summ]
    fig, ax = plt.subplots(figsize=(7, 3.6), dpi=170)
    bar_pair(ax, labels, [s["ucs_nodes"] for s in summ], [s["astar_nodes"] for s in summ], "UCS", "A*", C_UCS, C_ASTAR)
    ax.set_ylabel("Дундаж шалгасан зангилаа"); ax.set_title("UCS ба A*: шалгасан зангилаа", fontsize=11)
    plt.tight_layout(); plt.savefig(f"{OUT}/chart_nodes.png"); plt.close()

    fig, ax = plt.subplots(figsize=(7, 3.6), dpi=170)
    bar_pair(ax, labels, [s["ucs_ms"] for s in summ], [s["astar_ms"] for s in summ], "UCS", "A*", C_UCS, C_ASTAR, "{:.3f}")
    ax.set_ylabel("Дундаж хугацаа, мс"); ax.set_title("UCS ба A*: ажиллах хугацаа", fontsize=11)
    plt.tight_layout(); plt.savefig(f"{OUT}/chart_runtime.png"); plt.close()

    fig, ax = plt.subplots(figsize=(7, 3.6), dpi=170)
    bar_pair(ax, labels, [s["dist_route_avg_min"] for s in summ], [s["avg_trip_min"] for s in summ],
             "Зөвхөн зайгаар", "Түгжрэл тооцсон", C_UCS, C_ACC)
    ax.set_ylabel("Дундаж зорчих хугацаа, мин"); ax.set_title("Маршрутын сонголт: зай ба хугацаа", fontsize=11)
    plt.tight_layout(); plt.savefig(f"{OUT}/chart_distance_vs_time.png"); plt.close()

    fig, ax = plt.subplots(figsize=(7, 3.6), dpi=170)
    lab = [b["evidence"].replace(" / ", "\n") for b in bayes]
    bar_pair(ax, lab, [b["bayes_net"] for b in bayes], [b["sampling_mean"] for b in bayes],
             "Байесийн сүлжээ (= гар тооцоо)", "Түүвэрлэлт (1000 x 10)", C_ASTAR, C_UCS, "{:.2f}")
    ax.set_ylabel("P(түгжрэл = өндөр)"); ax.set_title("Магадлалын зөрүү", fontsize=11)
    plt.tight_layout(); plt.savefig(f"{OUT}/chart_probability.png"); plt.close()


def chart_routes(drows):
    big = [r for r in drows if r["graph"].startswith("scale")]
    conds = [c for c in dict.fromkeys(r["condition"] for r in big)]
    uni = [next(r["routes_changed_pct"] for r in big if r["condition"] == c and r["model"] == "uniform") for c in conds]
    cls = [next(r["routes_changed_pct"] for r in big if r["condition"] == c and r["model"] == "road_class") for c in conds]
    fig, ax = plt.subplots(figsize=(7, 3.6), dpi=170)
    bar_pair(ax, [c.replace("+", "\n") for c in conds], uni, cls, "Нэг загвар (XIII)", "Замын ангиллаар (XIV)", C_UCS, C_ACC)
    ax.set_ylabel("Өөрчлөгдсөн маршрут, %"); ax.set_title("Цэлмэг/оргил бус үетэй харьцуулахад өөрчлөгдсөн маршрут (64 зангилаа)", fontsize=10)
    plt.tight_layout(); plt.savefig(f"{OUT}/chart_route_changes.png"); plt.close()


def main():
    os.makedirs(OUT, exist_ok=True)
    g = Graph().load()
    pairs = pick_pairs(g)
    print(f"{len(pairs)} pairs x {len(CONDITIONS)} conditions x {REPEATS} repeats = {len(pairs)*len(CONDITIONS)*REPEATS} runs per algorithm")
    rows = run_search_experiments(g, pairs)
    summ = summarize(rows)
    bayes = bayes_check()
    write_csv(f"{OUT}/runs.csv", [{k: (round(v, 5) if isinstance(v, float) else v) for k, v in r.items()} for r in rows])
    write_csv(f"{OUT}/summary.csv", summ)
    write_csv(f"{OUT}/bayes_check.csv", bayes)
    charts(summ, bayes)
    drows = route_model_experiment()
    write_csv(f"{OUT}/route_model.csv", drows)
    chart_routes(drows)
    print("\n== A/B: search + route choice ==")
    for s in summ:
        print(f"{s['condition']:22} optimal {s['optimal_same']:9} nodes UCS {s['ucs_nodes']:5} A* {s['astar_nodes']:5} "
              f"(-{s['nodes_saved_pct']}%) | trip {s['avg_trip_min']} min vs dist-only {s['dist_route_avg_min']} min "
              f"(slower on {s['pairs_where_distance_route_is_slower']}/{N_PAIRS} pairs, avg -{s['avg_time_saved_pct']}%, max -{s['max_time_saved_pct']}%)")
    print("\n== C: probability P(high | evidence) ==")
    for b in bayes:
        print(f"{b['evidence']:28} hand {b['hand']}  BN {b['bayes_net']}  |diff| {b['hand_minus_bn']}  sampling {b['sampling_mean']} (err {b['sampling_mean_abs_err']})")
    print("\n== D: congestion model -> route changes vs clear+off_peak ==")
    for r in drows:
        print(f"{r['graph']:17} {r['model']:10} {r['condition']:19} changed {r['routes_changed']:5}/{r['pairs']} "
              f"({r['routes_changed_pct']:5}%) saved avg {r['avg_saved_pct_on_changed']:4}% max {r['max_saved_pct']:5}% | UCS=A* {r['ucs_eq_astar']}")
    print(f"\nSaved to {OUT}/")


if __name__ == "__main__":
    main()
