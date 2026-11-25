"""make_progress_week14.py - build progress_week14.pdf from the Week XII deck design.

Runs experiments.py (A-D) and the app.py demo, then fills the 8-slide template
(UBT_progress_week12.pptx) with the REAL numbers and exports the PDF with
LibreOffice (local, offline):

    python3 make_progress_week14.py
    -> results/*, UBT_progress_week14.pptx, progress_week14.pdf

Needs: soffice (LibreOffice), matplotlib (for experiments.py charts).
"""
import csv
import io
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from contextlib import redirect_stdout
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)

import experiments  # noqa: E402
import traffic  # noqa: E402
from make_progress_week13 import set_paras  # noqa: E402

TEMPLATE = "UBT_progress_week12.pptx"
OUT_PPTX, OUT_PDF = "UBT_progress_week14.pptx", "progress_week14.pdf"
COND_MN = {"clear+off_peak": "Цэлмэг, оргил бус", "rain+morning_peak": "Бороо, өглөө",
           "snow+morning_peak": "Цас, өглөө", "snow+evening_peak": "Цас, орой"}


def read_csv(p):
    return list(csv.DictReader(open(p, encoding="utf-8")))


def collect():
    with redirect_stdout(io.StringIO()):
        experiments.main()
    n = {"A": read_csv("results/summary.csv"), "C": read_csv("results/bayes_check.csv"),
         "D": read_csv("results/route_model.csv")}
    run = lambda *a: subprocess.run([sys.executable, "app.py", *a], capture_output=True, text=True, check=True).stdout
    n["demo"] = run("--from", "N04", "--to", "N05", "--weather", "snow", "--time", "evening", "peak", "--road-class")
    n["demo_off"] = run("--from", "N04", "--to", "N05", "--weather", "clear", "--time", "off-peak", "--road-class")
    return n


def d_row(n, graph, model, cond):
    return next(r for r in n["D"] if r["graph"].startswith(graph) and r["model"] == model and r["condition"] == cond)


def slide_chart(n, path):
    """Experiment D chart sized for the slide panel (bigger fonts than results/)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    big = [r for r in n["D"] if r["graph"].startswith("scale")]
    conds = list(dict.fromkeys(r["condition"] for r in big))
    val = lambda m: [float(next(r["routes_changed_pct"] for r in big if r["condition"] == c and r["model"] == m)) for c in conds]
    fig, ax = plt.subplots(figsize=(6.6, 4.0), dpi=200)
    x = range(len(conds))
    for off, vals, lab, col in [(-.2, val("uniform"), "Нэг загвар (XIII)", "#9aa2c0"), (.2, val("road_class"), "Замын ангиллаар (XIV)", "#e5473e")]:
        ax.bar([i + off for i in x], vals, .4, label=lab, color=col)
        for i, v in zip(x, vals):
            ax.text(i + off, v + .5, f"{v:.1f}", ha="center", va="bottom", fontsize=11, color="#1a1f3d")
    ax.set_xticks(list(x)); ax.set_xticklabels([COND_MN[c] for c in conds], fontsize=11, color="#1a1f3d")
    ax.set_ylabel("Өөрчлөгдсөн маршрут, %", fontsize=11, color="#1a1f3d")
    ax.set_title("Цэлмэг, оргил бус үетэй харьцуулахад (64 зангилаа)", fontsize=12, color="#1a1f3d")
    ax.spines[["top", "right"]].set_visible(False); ax.set_ylim(0, max(val("road_class")) * 1.18)
    ax.legend(frameon=False, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.1), fontsize=11)
    plt.tight_layout(); plt.savefig(path, transparent=True); plt.close()


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    return struct.unpack(">II", head[16:24])


def build(n):
    tmp = tempfile.mkdtemp()
    with zipfile.ZipFile(TEMPLATE) as z:
        z.extractall(tmp)
    rd = lambda p: open(os.path.join(tmp, p), encoding="utf-8").read()
    wr = lambda p, s: open(os.path.join(tmp, p), "w", encoding="utf-8").write(s)

    A = n["A"]
    runs = sum(int(r["runs"]) for r in A)
    same = sum(int(r["optimal_same"].split("/")[0]) for r in A)
    saved = [float(r["nodes_saved_pct"]) for r in A]
    big_c = d_row(n, "scale", "road_class", "snow+evening_peak")
    big_u = d_row(n, "scale", "uniform", "snow+evening_peak")
    city_c = d_row(n, "city", "road_class", "snow+evening_peak")
    max_saved = max(float(r["max_saved_pct"]) for r in n["D"] if r["graph"].startswith("scale") and r["model"] == "road_class")
    worstB = max(A, key=lambda r: float(r["max_time_saved_pct"]))
    max_err = max(float(r["sampling_mean_abs_err"]) for r in n["C"])
    max_diff = max(float(r["hand_minus_bn"]) for r in n["C"])
    m = re.search(r"Route : (.*)\n\s+Cost  : ([\d.]+) min \| expanded (\d+) nodes", n["demo"])
    route, cost, nodes = m.group(1), m.group(2), m.group(3)
    off = re.search(r"Route : (.*)\n\s+Cost  : ([\d.]+) min", n["demo_off"])
    bayes = re.search(r"P\(congestion low/medium/high\) = ([\d.]+) / ([\d.]+) / ([\d.]+)", n["demo"]).groups()
    K = traffic.ROAD_CLASS_K

    # 1 title
    s = rd("ppt/slides/slide1.xml")
    wr("ppt/slides/slide1.xml", s.replace("Явцийн тайлан · XII долоо хоног", "Явцийн тайлан · XIV долоо хоног"))

    # 2 done work
    s = rd("ppt/slides/slide2.xml")
    for old, badge, task, files in [
        ("X", "XII", "Ажилдаг хайлтын prototype", "app.py · progress_week12.pdf"),
        ("XI", "XIII", "Байесийн сүлжээ: цаг агаар, цаг → түгжрэл", "traffic.py · app.py --weather --time · progress_week13.pdf"),
        ("XII", "XIV", "Туршилт A–D, замын ангиллын загвар", "experiments.py · app.py --road-class · test_week14.py"),
    ]:
        s = set_paras(s, f"Badge text {old}", [badge])
        s = set_paras(s, f"Task {old}", [task])
        s = set_paras(s, f"File {old}", [files])
    wr("ppt/slides/slide2.xml", s)

    # 3 experiment D: chart image + stats
    s = rd("ppt/slides/slide3.xml")
    s = set_paras(s, "Text 0", ["ТУРШИЛТ D: МАРШРУТ"])
    chart = os.path.join(tmp, "slide_chart.png")
    slide_chart(n, chart)
    w_px, h_px = png_size(chart)
    fx, fy, fw, fh = 594360, 1143000, 5212080, 3108960   # area inside the white panel
    pw = fw
    ph = int(pw * h_px / w_px)
    if ph > fh:
        ph, pw = fh, int(fh * w_px / h_px)
    s = re.sub(r"<a:off x=\"594360\" y=\"1188720\"/>\s*<a:ext cx=\"5212080\" cy=\"3159343\"/>",
               f'<a:off x="{fx + (fw - pw) // 2}" y="{fy + (fh - ph) // 2}"/><a:ext cx="{pw}" cy="{ph}"/>', s)
    s = s.replace('descr="Замын графын газрын зураг: ногоон, шар, улаан нь түгжрэл, ягаан нь A* маршрут"',
                  'descr="Өөрчлөгдсөн маршрутын хувь: нэг загвар ба замын ангиллын загвар"')
    s = set_paras(s, "Stat 0", [f"{float(big_c['routes_changed_pct']):.0f}%"])
    s = set_paras(s, "Stat label 0", [f"маршрут өөрчлөгдсөн (XIII: {float(big_u['routes_changed_pct']):.0f}%)"])
    s = set_paras(s, "Stat 1", [f"−{max_saved:.1f}%"])
    s = set_paras(s, "Stat label 1", ["хугацааны их хэмнэлт"])
    s = set_paras(s, "Stat 2", [f"{float(city_c['routes_changed_pct']):.1f}%"])
    s = set_paras(s, "Stat label 2", ["15 зангилаат граф дээр"])
    wr("ppt/slides/slide3.xml", s)
    shutil.move(chart, os.path.join(tmp, "ppt/media/image-3-1.png"))

    # 4 experiments B and C + road-class formula
    s = rd("ppt/slides/slide4.xml")
    s = set_paras(s, "Text 0", ["ТУРШИЛТ B, C"])
    s = set_paras(s, "UCS title", ["B: зай ба хугацаа"])
    s = set_paras(s, "UCS text", [
        f"Зөвхөн зайн маршрут ≤{max(int(r['pairs_where_distance_route_is_slower']) for r in A)}/{experiments.N_PAIRS} хосод удаан",
        f"Дундаж −{max(float(r['avg_time_saved_pct']) for r in A):.1f}%, их нь −{float(worstB['max_time_saved_pct']):.1f}% ({COND_MN[worstB['condition']].lower()})",
        "15 зангилаа: өөр зам цөөн тул ялгаа бага"])
    s = set_paras(s, "A* title", ["C: магадлалын шалгалт"])
    s = set_paras(s, "A* text", [
        f"Гар тооцоо = BN, зөрүү ≤ {max_diff:.1e}",
        f"Түүвэрлэлт 1000 × 10: алдаа ≤ {max_err:.4f}",
        f"{len(n['C'])} асуулга, нөхцөлтэй ба нөхцөлгүй"])
    s = set_paras(s, "Travel time formula",
                  [f"c = clip( base + k · Δ ),  k: төв гудамж {K['local']} · гол зам {K['main']} · тойруу {K['arterial']}"])
    s = s.replace('sz="2000"', 'sz="1700"') if "Travel time formula" in s else s
    wr("ppt/slides/slide4.xml", s)

    # 5 experiment A: chart with 4 conditions
    s = rd("ppt/slides/slide5.xml")
    s = set_paras(s, "Text 0", ["ТУРШИЛТ A: UCS ба A*"])
    s = set_paras(s, "Optimal count", [f"{same}/{runs}"])
    s = set_paras(s, "Optimal label", [f"{experiments.N_PAIRS} хос × 4 нөхцөл × {experiments.REPEATS}: ижил оновчтой өртөг"])
    s = set_paras(s, "Saving", [f"−{min(saved):.0f}…{max(saved):.0f}%"])
    s = set_paras(s, "Saving label", ["A*-ийн шалгасан зангилаа, 4 нөхцөлд"])
    wr("ppt/slides/slide5.xml", s)
    cats = [COND_MN[r["condition"]] for r in A]
    ucs_v = [r["ucs_nodes"] for r in A]
    ast_v = [r["astar_nodes"] for r in A]
    ch = rd("ppt/charts/chart1.xml")
    ch = ch.replace("<a:t>Дундаж шалгасан зангилаа</a:t>", "<a:t>Дундаж шалгасан зангилаа (15 зангилаа)</a:t>")
    cat_xml = '<c:ptCount val="4"/><c:lvl>' + "".join(
        f'<c:pt idx="{i}"><c:v>{escape(c)}</c:v></c:pt>' for i, c in enumerate(cats)) + "</c:lvl>"
    ch = re.sub(r'<c:ptCount val="2"/><c:lvl>.*?</c:lvl>', lambda _m: cat_xml, ch, flags=re.S)
    ch = ch.replace("Sheet1!$A$2:$A$3", "Sheet1!$A$2:$A$5").replace("Sheet1!$B$2:$B$3", "Sheet1!$B$2:$B$5") \
           .replace("Sheet1!$C$2:$C$3", "Sheet1!$C$2:$C$5")
    vals = iter([ucs_v, ast_v])
    ch = re.sub(r'<c:ptCount val="2"/><c:pt idx="0"><c:v>[\d.]+</c:v></c:pt><c:pt idx="1"><c:v>[\d.]+</c:v></c:pt>',
                lambda _m: '<c:ptCount val="4"/>' + "".join(f'<c:pt idx="{i}"><c:v>{v}</c:v></c:pt>'
                                                            for i, v in enumerate(next(vals))), ch)
    wr("ppt/charts/chart1.xml", ch)
    xl = os.path.join(tmp, "ppt/embeddings/Microsoft_Excel_Worksheet1.xlsx")
    with zipfile.ZipFile(xl) as z:
        files = {i: z.read(i) for i in z.namelist()}
    sh = files["xl/worksheets/sheet1.xml"].decode()
    rows = "".join(
        f'<row r="{i + 2}" spans="1:3"><c r="A{i + 2}" t="inlineStr"><is><t>{escape(c)}</t></is></c>'
        f'<c r="B{i + 2}"><v>{u}</v></c><c r="C{i + 2}"><v>{a}</v></c></row>'
        for i, (c, u, a) in enumerate(zip(cats, ucs_v, ast_v)))
    sh = re.sub(r'<row r="2".*</row>', rows, sh, flags=re.S).replace('<dimension ref="A1:C3"/>', '<dimension ref="A1:C5"/>')
    files["xl/worksheets/sheet1.xml"] = sh.encode()
    for name in list(files):
        if name.startswith("xl/tables/"):
            files[name] = files[name].replace(b"A1:C3", b"A1:C5")
    with zipfile.ZipFile(xl, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in files.items():
            z.writestr(k, v)

    # 6 demo
    s = rd("ppt/slides/slide6.xml")
    s = s.replace("<a:t>PROTOTYPE: app.py</a:t>", "<a:t>DEMO: --road-class</a:t>")
    stops = route.split(" -> ")
    s = set_paras(s, "Terminal text", [
        ("$ python3 app.py --from N04 --to N05 \\", 0),
        ("    --weather snow --time evening peak \\", 0),
        ("    --road-class", 0),
        (f"[Bayes] P(low/med/high) = {'/'.join(bayes)}", 2),
        (f"[A*]   {cost} min | {nodes} nodes", 3),
        (" ", 1),
        (f"{stops[0]} ->", 5),
        ("  " + " -> ".join(stops[1:3]) + " ->", 6),
        ("  " + " -> ".join(stops[3:]), 7),
        (" ", 8),
        (f"цэлмэг, оргил бус: {off.group(2)} min,", 5),
        ("  via " + " -> ".join(off.group(1).split(" -> ")[1:-1]), 5),
    ], size=1200)
    s = set_paras(s, "Options title", ["--road-class"])
    s = set_paras(s, "Options list", [f"Төв гудамж (≤40 км/ц) ×{K['local']}",
                                      f"Гол зам (50 км/ц) ×{K['main']}",
                                      f"Тойруу (≥60 км/ц) ×{K['arterial']}",
                                      "Цас, оргил үед төвөөс тойруу руу шилжинэ",
                                      "--weather/--time-гүй бол алдаа өгнө"])
    wr("ppt/slides/slide6.xml", s)

    # 7 next steps
    s = rd("ppt/slides/slide7.xml")
    s = set_paras(s, "Next title", ["XV долоо хоног"])
    s = set_paras(s, "Next list", ["Эцсийн тайлан, илтгэл",
                                   "Хэдэн аяллын хугацааг хэмжиж CPD, k-г тааруулах",
                                   "OSM граф дээр бүх туршилт",
                                   "Хугацааны хүлээгдэх утга E[t]-г турших"])
    s = set_paras(s, "Risk list", ["CPD, k нь таамаг: бодит өгөгдөл хэрэгтэй",
                                   f"15 зангилаат граф жижиг: маршрут {float(city_c['routes_changed_pct']):.1f}%-д л өөрчлөгдөнө",
                                   f"Жижиг граф дээр A* мс-ээр удаан: A* {A[0]['astar_ms']}, UCS {A[0]['ucs_ms']} мс (h тооцоо)"])
    wr("ppt/slides/slide7.xml", s)

    notes = {
        1: "Нээлт: XIV долоо хоногийн явцийн тайлан.",
        2: "XII, XIII, XIV долоо хоногийн ажил бүгд дууссан.",
        3: f"64 зангилаатай граф, {big_c['pairs']} хос. Цас, оройн оргил үед замын ангиллын загвар {big_c['routes_changed']} маршрутыг өөрчилсөн.",
        4: "B: зөвхөн зайгаар сонгосон маршрутыг түгжрэл тооцсон маршруттай харьцуулав. C: гар тооцоо, BN, түүвэрлэлт.",
        5: f"{runs} ажиллуулалт бүгдэд UCS = A*. A* {min(saved):.0f}–{max(saved):.0f}% цөөн зангилаа шалгасан.",
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
    for r in n["A"]:
        print(f"A {r['condition']:18} optimal {r['optimal_same']} nodes UCS {r['ucs_nodes']} A* {r['astar_nodes']} (-{r['nodes_saved_pct']}%)")
    for r in n["D"]:
        if r["graph"].startswith("scale") and r["condition"] == "snow+evening_peak":
            print(f"D {r['graph']} {r['model']:10} changed {r['routes_changed']}/{r['pairs']} ({r['routes_changed_pct']}%)")
    print(f"wrote {OUT_PPTX} and {OUT_PDF}")


if __name__ == "__main__":
    main()
