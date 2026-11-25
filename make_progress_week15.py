"""make_progress_week15.py - build progress_week15.pdf from the Week XII deck design.

Runs experiments_week15.py (E1-E3), the calibration recovery study and the
OSM demo, then fills the 8-slide template (UBT_progress_week12.pptx) with the
REAL numbers and exports the PDF with LibreOffice (local, offline):

    python3 make_progress_week15.py
    -> results/week15_*.csv, results/calibration_recovery.csv,
       UBT_progress_week15.pptx, progress_week15.pdf

Needs: soffice (LibreOffice), matplotlib. Map data: OpenStreetMap contributors (ODbL).
"""
import csv
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from contextlib import redirect_stdout
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)

import calibrate  # noqa: E402
import experiments_week15 as X  # noqa: E402
import traffic as T  # noqa: E402
from graph import Graph  # noqa: E402
from make_progress_week13 import set_paras  # noqa: E402
from make_progress_week14 import png_size  # noqa: E402
from search import astar  # noqa: E402

TEMPLATE = "UBT_progress_week12.pptx"
OUT_PPTX, OUT_PDF = "UBT_progress_week15.pptx", "progress_week15.pdf"
DEMO = ("N0674", "N1275")


def collect():
    n = {}
    with redirect_stdout(io.StringIO()):
        n["E1"], n["E2"], n["E3"] = X.main()
    g = Graph().load()
    n["recovery"] = calibrate.recovery_study(g)
    with open("results/calibration_recovery.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(n["recovery"][0]))
        w.writeheader(); w.writerows(n["recovery"])
    run = lambda *a: subprocess.run([sys.executable, "app.py", "--data", "data_osm", "--from", DEMO[0], "--to", DEMO[1],
                                     "--road-class", "--roads", *a], capture_output=True, text=True, check=True).stdout
    n["snow"] = run("--weather", "snow", "--time", "evening", "peak")
    n["clear"] = run("--weather", "clear", "--time", "off-peak")
    go = Graph().load("data_osm/nodes.csv", "data_osm/edges.csv")
    off = T.apply_conditions(go, "clear", "off_peak", by_class=True)
    bad = T.apply_conditions(go, "snow", "evening_peak", by_class=True)
    p_off, _, _ = astar(off, *DEMO)
    p_bad, _, _ = astar(bad, *DEMO)
    n["old_route_snow"] = X.path_time(bad, p_off)
    n["osm"] = go
    n["routes"] = (p_off, p_bad)
    with open("data_osm/edges.csv", encoding="utf-8") as f:
        n["km"] = sum(float(r["length_km"]) for r in csv.DictReader(f))
    return n


def parse(out):
    m = re.search(r"Roads : (.*) \((\d+) stops\)\n\s+Cost  : ([\d.]+) min \| expanded (\d+) nodes", out)
    return dict(roads=m.group(1).split(" -> "), stops=m.group(2), cost=m.group(3), nodes=m.group(4))


def map_png(n, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    g = n["osm"]
    fig, ax = plt.subplots(figsize=(6.6, 4.0), dpi=200)
    # crop to the demo routes (+ margin) so the city centre is readable
    pts = [g.nodes[i] for r in n["routes"] for i in r]
    la0, la1 = min(p[1] for p in pts), max(p[1] for p in pts)
    lo0, lo1 = min(p[2] for p in pts), max(p[2] for p in pts)
    cla, clo = (la0 + la1) / 2, (lo0 + lo1) / 2
    half_la = max(la1 - la0, (lo1 - lo0) * 0.67 / 1.65) / 2 + 0.006
    half_lo = half_la * 1.65 / 0.67
    for e in g.edges:
        (_, la, lo), (_, lb, lob) = g.nodes[e["src"]], g.nodes[e["dst"]]
        ax.plot([lo, lob], [la, lb], color="#9aa2c0", lw=0.8, zorder=1)
    ax.set_xlim(clo - half_lo, clo + half_lo); ax.set_ylim(cla - half_la, cla + half_la)
    for route, col, lab in [(n["routes"][0], "#5b52a8", "цэлмэг, оргил бус"), (n["routes"][1], "#e5473e", "цас, оройн оргил")]:
        ax.plot([g.nodes[i][2] for i in route], [g.nodes[i][1] for i in route], color=col, lw=2.4, label=lab, zorder=3)
    s, t = (g.nodes[i] for i in DEMO)
    ax.scatter([s[2], t[2]], [s[1], t[1]], color="#1a1f3d", s=18, zorder=4)
    ax.set_aspect(1 / 0.67, adjustable="box")  # cos(47.9 deg) ~ 0.67: keep the map undistorted
    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.legend(frameon=False, loc="lower left", fontsize=10)
    ax.text(0.99, 0.01, "© OpenStreetMap contributors, ODbL", transform=ax.transAxes, ha="right", va="bottom",
            fontsize=7, color="#5d647d")
    plt.tight_layout(); plt.savefig(path, transparent=True); plt.close()


def build(n):
    tmp = tempfile.mkdtemp()
    with zipfile.ZipFile(TEMPLATE) as z:
        z.extractall(tmp)
    rd = lambda p: open(os.path.join(tmp, p), encoding="utf-8").read()
    wr = lambda p, s: open(os.path.join(tmp, p), "w", encoding="utf-8").write(s)

    e1 = next(r for r in n["E1"] if r["condition"] == "default")
    e1_all_ok = all(r["optimal_same"].split("/")[0] == r["optimal_same"].split("/")[1] for r in n["E1"])
    e2c = next(r for r in n["E2"] if r["model"] == "road_class" and r["condition"] == "snow+evening_peak")
    e2u = next(r for r in n["E2"] if r["model"] == "uniform" and r["condition"] == "snow+evening_peak")
    e3 = n["E3"]
    inc = [r["avg_cost_increase_pct"] for r in e3]
    rdiff = max(r["routes_different_pct"] for r in e3)
    rec = {r["trips"]: r for r in n["recovery"]}
    big = rec[max(rec)]
    snow, clear = parse(n["snow"]), parse(n["clear"])
    go = n["osm"]
    pairs = e1["pairs"]

    # 1 title
    s = rd("ppt/slides/slide1.xml")
    wr("ppt/slides/slide1.xml", s.replace("Явцийн тайлан · XII долоо хоног", "Явцийн тайлан · XV долоо хоног"))

    # 2 done work
    s = rd("ppt/slides/slide2.xml")
    for old, badge, task, files in [
        ("X", "XIII", "Байесийн сүлжээ: цаг агаар, цаг → түгжрэл", "traffic.py · app.py --weather --time"),
        ("XI", "XIV", "Туршилт A–D, замын ангиллын загвар", "experiments.py · app.py --road-class"),
        ("XII", "XV", "Бодит OSM граф, E[хугацаа], калибровк", "data_osm · experiments_week15.py · calibrate.py"),
    ]:
        s = set_paras(s, f"Badge text {old}", [badge])
        s = set_paras(s, f"Task {old}", [task])
        s = set_paras(s, f"File {old}", [files])
    wr("ppt/slides/slide2.xml", s)

    # 3 real OSM graph: map + stats
    s = rd("ppt/slides/slide3.xml")
    s = set_paras(s, "Text 0", ["БОДИТ ГРАФ: OPENSTREETMAP"])
    img = os.path.join(tmp, "map.png")
    map_png(n, img)
    w_px, h_px = png_size(img)
    fx, fy, fw, fh = 594360, 1143000, 5212080, 3108960
    pw, ph = fw, int(fw * h_px / w_px)
    if ph > fh:
        ph, pw = fh, int(fh * w_px / h_px)
    s = re.sub(r"<a:off x=\"594360\" y=\"1188720\"/>\s*<a:ext cx=\"5212080\" cy=\"3159343\"/>",
               f'<a:off x="{fx + (fw - pw) // 2}" y="{fy + (fh - ph) // 2}"/><a:ext cx="{pw}" cy="{ph}"/>', s)
    s = s.replace('descr="Замын графын газрын зураг: ногоон, шар, улаан нь түгжрэл, ягаан нь A* маршрут"',
                  'descr="Улаанбаатарын OSM замын граф ба хоёр нөхцөлийн маршрут"')
    s = set_paras(s, "Stat 0", [f"{len(go.nodes)}"])
    s = set_paras(s, "Stat label 0", ["зангилаа (XII: 15)"])
    s = set_paras(s, "Stat 1", [f"{len(go.edges)}"])
    s = set_paras(s, "Stat label 1", ["чиглэлтэй ирмэг"])
    s = set_paras(s, "Stat 2", [f"≈{n['km']:.0f} км"])
    s = set_paras(s, "Stat label 2", ["бодит урттай зам"])
    wr("ppt/slides/slide3.xml", s)
    shutil.move(img, os.path.join(tmp, "ppt/media/image-3-1.png"))

    # 4 E[t] + calibration
    s = rd("ppt/slides/slide4.xml")
    s = set_paras(s, "Text 0", ["E[ХУГАЦАА], КАЛИБРОВК"])
    s = set_paras(s, "UCS title", ["Хүлээгдэх хугацаа"])
    s = set_paras(s, "UCS text", [
        "E[t] ≥ t(E[c]): түгжрэл ихсэхэд хугацаа хурдан өснө",
        f"Дунджаар +{min(inc):.1f}…{max(inc):.1f}% (3 граф, 2 нөхцөл)",
        f"Маршрут ≤{rdiff:.1f}% хосод өөр, UCS = A* хэвээр"])
    s = set_paras(s, "A* title", ["calibrate.py"])
    s = set_paras(s, "A* text", [
        "Хэмжсэн аяллаас k-г RMSE-ээр тааруулна",
        f"Синтетик шалгалт: төв гудамжийн k алдаа 60 аялалд {rec[60]['mean_abs_err_local']:.2f}, "
        f"{big['trips']}-д {big['mean_abs_err_local']:.2f}",
        f"Гол зам, тойруугийн k 60 аялалд ч ойр ({rec[60]['mean_abs_err_main']:.2f}, {rec[60]['mean_abs_err_arterial']:.2f})"])
    s = set_paras(s, "Travel time formula", ["E[t] = Σ P(l | W,T) · зай ÷ ( хурд × (1 − 0.7 · c_l) )"])
    wr("ppt/slides/slide4.xml", s)

    # 5 E1 on OSM: same metric as Week XII
    s = rd("ppt/slides/slide5.xml")
    s = set_paras(s, "Text 0", ["ТУРШИЛТ: OSM ГРАФ"])
    total = sum(int(r["optimal_same"].split("/")[1]) for r in n["E1"])
    s = set_paras(s, "Optimal count", [f"{total}/{total}" if e1_all_ok else "NO"])
    s = set_paras(s, "Optimal label", [f"{pairs} хос × 5 нөхцөл × хугацаа/зай: UCS = A*"])
    s = set_paras(s, "Saving", [f"−{round(e1['reduction_time_pct'])}% / −{round(e1['reduction_dist_pct'])}%"])
    s = set_paras(s, "Saving label", ["A*-ийн шалгасан зангилаа: хугацаа / зай (XII: −17% / −34%)"])
    wr("ppt/slides/slide5.xml", s)
    ch = rd("ppt/charts/chart1.xml")
    ch = ch.replace("<a:t>Дундаж шалгасан зангилаа</a:t>", f"<a:t>Дундаж шалгасан зангилаа (OSM, {pairs} хос)</a:t>")
    vals = [e1["ucs_nodes_time"], e1["ucs_nodes_dist"], e1["astar_nodes_time"], e1["astar_nodes_dist"]]
    it = iter(vals)
    ch = re.sub(r'(<c:pt idx="[01]"><c:v>)([\d.]+)(</c:v></c:pt>)', lambda m: f"{m.group(1)}{next(it)}{m.group(3)}", ch)
    ch = ch.replace('<c:max val="10"/>', '<c:max val="1000"/>').replace('formatCode="0.0"', 'formatCode="0"')
    wr("ppt/charts/chart1.xml", ch)
    xl = os.path.join(tmp, "ppt/embeddings/Microsoft_Excel_Worksheet1.xlsx")
    with zipfile.ZipFile(xl) as z:
        files = {i: z.read(i) for i in z.namelist()}
    sh = files["xl/worksheets/sheet1.xml"].decode()
    for cell, v in zip(["B2", "B3", "C2", "C3"], vals):
        sh = re.sub(rf'(<c r="{cell}"><v>)[\d.]+(</v>)', rf"\g<1>{v}\g<2>", sh)
    files["xl/worksheets/sheet1.xml"] = sh.encode()
    with zipfile.ZipFile(xl, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in files.items():
            z.writestr(k, v)

    # 6 demo on OSM
    s = rd("ppt/slides/slide6.xml")
    s = s.replace("<a:t>PROTOTYPE: app.py</a:t>", "<a:t>DEMO: БОДИТ ГРАФ</a:t>")
    mid = [r for r in snow["roads"][1:-1] if r != snow["roads"][-1]]
    mid = list(dict.fromkeys(mid))[:2]
    cmid = list(dict.fromkeys(clear["roads"][1:-1]))[:2]
    s = set_paras(s, "Terminal text", [
        ("$ python3 app.py --data data_osm --roads \\", 0),
        (f"   --from {DEMO[0]} --to {DEMO[1]} --road-class \\", 0),
        ("   --weather snow --time evening peak", 0),
        (f"[A*]  {snow['cost']} min | {snow['nodes']} nodes", 3),
        ("Roads: " + snow["roads"][0] + " ->", 5),
        ("  " + " -> ".join(mid) + " ->", 6),
        ("  " + snow["roads"][-1], 7),
        (" ", 8),
        (f"clear, off-peak: {clear['cost']} min", 5),
        ("  " + " -> ".join(cmid) + " ...", 6),
        (f"хуучин маршрут цасанд: {n['old_route_snow']:.2f} min", 9),
    ], size=1150)
    s = set_paras(s, "Options title", ["Шинэ сонголтууд"])
    s = set_paras(s, "Options list", ["--data data_osm: бодит граф",
                                      "--roads: замын нэрс",
                                      "--expected-time: E[хугацаа]",
                                      "--k-file: тааруулсан k",
                                      "Татсан OSM файл: офлайн"])
    wr("ppt/slides/slide6.xml", s)

    # 7 next steps
    s = rd("ppt/slides/slide7.xml")
    s = set_paras(s, "Next title", ["XVI долоо хоног"])
    s = set_paras(s, "Next list", ["Эцсийн тайлан, илтгэл",
                                   "Бодит аялал хэмжиж calibrate.py-д оруулах",
                                   "OSM замуудын суурь түгжрэлийг хэмжих",
                                   "README, код цэгцлэх"])
    s = set_paras(s, "Risk list", ["CPD, base, k нь таамаг хэвээр",
                                   f"Төв гудамжийн k-г тогтооход ~{big['trips']} аялал хэрэгтэй",
                                   "OSM нэр холимог (монгол / англи)"])
    wr("ppt/slides/slide7.xml", s)

    notes = {
        1: "Нээлт: XV долоо хоногийн явцийн тайлан.",
        2: "XIII, XIV, XV долоо хоногийн ажил бүгд дууссан.",
        3: f"OpenStreetMap-аас татсан бодит граф. Цас, оройн оргил үед {e2c['routes_changed_pct']}% маршрут өөрчлөгдсөн "
           f"(нэг загвар: {e2u['routes_changed_pct']}%).",
        4: "E[t] нь хугацааны хүлээгдэх утга. Калибровк нь синтетик өгөгдлөөр шалгагдсан; бодит аялал хэрэгтэй.",
        5: f"{pairs} санамсаргүй хос, XII-тэй ижил аргаар. Бүх нөхцөлд UCS = A*.",
        6: "Terminal дээр шууд ажиллуулж үзүүлнэ: эхлээд цэлмэг, дараа нь цас + орой.",
    }
    for i, t in notes.items():
        path = f"ppt/notesSlides/notesSlide{i}.xml"
        x = rd(path)
        wr(path, re.sub(r"<a:t>[^<]*[^\d<][^<]*</a:t>", f"<a:t>{escape(t)}</a:t>", x, count=1))

    if os.path.exists(OUT_PPTX):
        os.remove(OUT_PPTX)
    with zipfile.ZipFile(OUT_PPTX, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(tmp, "[Content_Types].xml"), "[Content_Types].xml")
        for root, _, fs in os.walk(tmp):
            for f in fs:
                full = os.path.join(root, f)
                arc = os.path.relpath(full, tmp)
                if arc != "[Content_Types].xml":
                    z.write(full, arc)
    shutil.rmtree(tmp)
    outdir = tempfile.mkdtemp()
    subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", outdir, OUT_PPTX],
                   check=True, capture_output=True, timeout=300)
    shutil.move(os.path.join(outdir, OUT_PPTX.replace(".pptx", ".pdf")), OUT_PDF)
    shutil.rmtree(outdir)


def main():
    n = collect()
    build(n)
    e1 = next(r for r in n["E1"] if r["condition"] == "default")
    print(f"E1 OSM default: UCS {e1['ucs_nodes_time']}/{e1['ucs_nodes_dist']} A* {e1['astar_nodes_time']}/{e1['astar_nodes_dist']} "
          f"-> -{e1['reduction_time_pct']}% / -{e1['reduction_dist_pct']}%")
    print("demo snow:", parse(n["snow"])["cost"], "clear:", parse(n["clear"])["cost"], f"old route in snow: {n['old_route_snow']:.2f}")
    print(f"wrote {OUT_PPTX} and {OUT_PDF}")


if __name__ == "__main__":
    main()
