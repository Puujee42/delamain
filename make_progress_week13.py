"""make_progress_week13.py - build progress_week13.pdf from the Week XII deck.

Takes UBT_progress_week12.pptx (same 8-slide design), replaces the text with
Week XIII content and fills every number from REAL runs of the code
(traffic.py tests, scale_test.py, app.py demo), then exports the PDF with
LibreOffice (local, offline):

    python3 make_progress_week13.py
    -> UBT_progress_week13.pptx, progress_week13.pdf

Needs: soffice (LibreOffice) on PATH. Standard library only.
"""
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

import scale_test  # noqa: E402
import traffic  # noqa: E402
from graph import Graph  # noqa: E402
from search import astar  # noqa: E402

TEMPLATE = "UBT_progress_week12.pptx"
OUT_PPTX, OUT_PDF = "UBT_progress_week13.pptx", "progress_week13.pdf"


# ------------------------------------------------------------ real numbers
def collect():
    n = {}
    buf = io.StringIO()
    with redirect_stdout(buf):
        n["traffic_ok"] = traffic.run_tests()
    log = buf.getvalue()
    n["traffic_pass"] = log.count("[PASS]")
    n["pair_checks"] = re.findall(r"UCS == A\* on all (\d+) pairs.*mismatches: (\d+)", log)
    assert n["traffic_ok"] and all(m == "0" for _, m in n["pair_checks"]), log

    with redirect_stdout(io.StringIO()):
        rows = scale_test.main()
    n["scale"] = {(r["graph"], r["condition"]): r for r in rows}

    r = subprocess.run([sys.executable, "app.py", "--from", "N01", "--to", "N15", "--compare",
                        "--weather", "snow", "--time", "morning", "peak"],
                       capture_output=True, text=True, check=True)
    n["demo_out"] = r.stdout
    d = subprocess.run([sys.executable, "app.py", "--from", "N01", "--to", "N15", "--compare"],
                       capture_output=True, text=True, check=True)
    n["default_out"] = d.stdout

    g = Graph().load()
    gs = traffic.apply_conditions(g, "snow", "morning_peak")
    e0 = next(e for e in g.edges if e["src"] == "N01" and e["dst"] == "N02")
    e1 = next(e for e in gs.edges if e["src"] == "N01" and e["dst"] == "N02")
    n["edge"] = (e0["congestion"], e1["congestion"], e0["time_min"], e1["time_min"])

    ids = list(g.nodes)
    base = {(s, t): astar(g, s, t)[0] for s in ids for t in ids if s != t}
    n["route_changes"] = max(
        sum(astar(traffic.apply_conditions(g, w, tm), s, t)[0] != p for (s, t), p in base.items())
        for w in traffic.WEATHER for tm in traffic.TIME)
    return n


def parse_compare(out):
    costs = re.findall(r"Cost  : ([\d.]+) min \| expanded (\d+) nodes", out)
    route = re.search(r"Route : (.*)", out).group(1)
    return costs, route


# ------------------------------------------------------------ pptx helpers
def shape_span(xml, name):
    """(start, end) of the <p:sp> whose cNvPr name is `name`."""
    i = xml.index(f'name="{name}"')
    s = xml.rfind("<p:sp>", 0, i)
    return s, xml.index("</p:sp>", i) + len("</p:sp>")


def set_paras(xml, name, texts, size=None):
    """Replace the paragraphs of shape `name` with `texts`, re-using the
    formatting of the existing paragraphs (the last one is cloned if more
    are needed). A text may be (text, template_index)."""
    s, e = shape_span(xml, name)
    sp = xml[s:e]
    paras = re.findall(r"<a:p>.*?</a:p>", sp, flags=re.S)
    new = []
    for k, t in enumerate(texts):
        t, idx = t if isinstance(t, tuple) else (t, min(k, len(paras) - 1))
        p = paras[idx]
        p = re.sub(r"<a:t>.*?</a:t>", lambda _m: f"<a:t>{escape(t)}</a:t>", p, count=1, flags=re.S)
        # drop any extra runs after the first one
        first = p.index("</a:r>") + len("</a:r>")
        rest = p[first:]
        rest = re.sub(r"<a:r>.*?</a:r>", "", rest, flags=re.S)
        p = p[:first] + rest
        if size:
            p = re.sub(r'sz="\d+"', f'sz="{size}"', p)
        new.append(p)
    body_s = sp.index(paras[0])
    body_e = sp.rindex(paras[-1]) + len(paras[-1])
    sp = sp[:body_s] + "".join(new) + sp[body_e:]
    return xml[:s] + sp + xml[e:]


def box(id_, name, x, y, w, h, fill, title, sub, title_color="FFFFFF", sub_color="FFFFFF"):
    run = lambda t, sz, b, c: (
        f'<a:p><a:pPr algn="ctr" indent="0" marL="0"><a:buNone/></a:pPr><a:r><a:rPr lang="mn-MN" sz="{sz}" b="{b}" dirty="0">'
        f'<a:solidFill><a:srgbClr val="{c}"/></a:solidFill><a:latin typeface="Arial"/><a:cs typeface="Arial"/></a:rPr>'
        f"<a:t>{escape(t)}</a:t></a:r></a:p>")
    subs = "".join(run(s, 1000, 0, sub_color) for s in sub)
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{id_}" name="{name}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>'
            f'<a:prstGeom prst="roundRect"><a:avLst><a:gd name="adj" fmla="val 18000"/></a:avLst></a:prstGeom>'
            f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill><a:ln><a:noFill/></a:ln></p:spPr>'
            f'<p:txBody><a:bodyPr wrap="square" lIns="45720" tIns="45720" rIns="45720" bIns="45720" anchor="ctr"/><a:lstStyle/>'
            f"{run(title, 1500, 1, title_color)}{subs}</p:txBody></p:sp>")


def text(id_, name, x, y, w, h, lines, sz=1100, color="1A1F3D", algn="l", bold=0):
    ps = "".join(
        f'<a:p><a:pPr algn="{algn}" indent="0" marL="0"><a:buNone/></a:pPr><a:r><a:rPr lang="mn-MN" sz="{sz}" b="{bold}" dirty="0">'
        f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill><a:latin typeface="Arial"/><a:cs typeface="Arial"/></a:rPr>'
        f"<a:t>{escape(t)}</a:t></a:r></a:p>" for t in lines)
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{id_}" name="{name}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
            f'<a:noFill/></p:spPr><p:txBody><a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" anchor="t"/><a:lstStyle/>{ps}</p:txBody></p:sp>')


def arrow(id_, x, y, w, h, flip_v=False):
    fv = ' flipV="1"' if flip_v else ""
    return (f'<p:cxnSp><p:nvCxnSpPr><p:cNvPr id="{id_}" name="Arrow {id_}"/><p:cNvCxnSpPr/><p:nvPr/></p:nvCxnSpPr>'
            f'<p:spPr><a:xfrm{fv}><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="straightConnector1"><a:avLst/></a:prstGeom>'
            f'<a:ln w="28575"><a:solidFill><a:srgbClr val="1A1F3D"/></a:solidFill><a:tailEnd type="triangle" w="med" len="med"/></a:ln></p:spPr></p:cxnSp>')


def bn_diagram():
    """Bayesian network drawn with native shapes inside the white map panel
    (panel: x 457200..5943600, y 1051560..4343400)."""
    P, T = traffic.P_WEATHER, traffic.P_TIME
    purple, red, dark = "5B52A8", "E5473E", "1A1F3D"
    return "".join([
        text(40, "BN formula", 640080, 1143000, 5120640, 274320,
             ["P(W, T, C) = P(W) · P(T) · P(C | W, T)"], sz=1300, bold=1, algn="ctr"),
        box(41, "Node W", 640080, 1554480, 2194560, 868680, purple, "Цаг агаар (W)",
            [f"цэлмэг {P['clear']:.2f} · цас {P['snow']:.2f}", f"бороо {P['rain']:.2f}"]),
        box(42, "Node T", 640080, 3017520, 2194560, 868680, purple, "Өдрийн цаг (T)",
            [f"оргил бус {T['off_peak']:.2f}", f"өглөө {T['morning_peak']:.2f} · орой {T['evening_peak']:.2f}"]),
        box(43, "Node C", 3566160, 2286000, 2194560, 868680, red, "Түгжрэл (C)",
            ["бага · дунд · их", f"P(C | W, T): {len(traffic.CPD_CONG)} мөр"]),
        arrow(44, 2834640, 1988820, 731520, 731520),
        arrow(45, 2834640, 2720340, 731520, 731520, flip_v=True),
        text(46, "BN edge note", 3566160, 3246120, 2194560, 960120,
             ["↓ ирмэг бүрт", "E[cₑ] = Σ P(l | W,T)·(base + Δl)", "→ ирмэгийн хугацаа"],
             sz=1050, color=dark, algn="ctr"),
    ])


# ------------------------------------------------------------ build
def build(n):
    tmp = tempfile.mkdtemp()
    with zipfile.ZipFile(TEMPLATE) as z:
        z.extractall(tmp)
    rd = lambda p: open(os.path.join(tmp, p), encoding="utf-8").read()
    wr = lambda p, s: open(os.path.join(tmp, p), "w", encoding="utf-8").write(s)

    city = n["scale"][("city (15 nodes)", "default")]
    big = n["scale"][("scale (64 nodes)", "default")]
    big_cond = [r for (gname, c), r in n["scale"].items() if gname.startswith("scale") and c != "default"]
    pct = lambda r: f"−{round(r['reduction_time_pct'])}% / −{round(r['reduction_dist_pct'])}%"
    costs, route = parse_compare(n["demo_out"])
    dcosts, _ = parse_compare(n["default_out"])
    p = traffic.CPD_CONG[("snow", "morning_peak")]
    c0, c1, t0, t1 = n["edge"]
    pairs = int(n["pair_checks"][0][0])
    nconds = len(n["pair_checks"])
    bayes = re.search(r"P\(congestion low/medium/high\) = ([\d.]+) / ([\d.]+) / ([\d.]+)", n["demo_out"]).groups()

    # 1 title
    s = rd("ppt/slides/slide1.xml")
    s = s.replace("Явцийн тайлан · XII долоо хоног", "Явцийн тайлан · XIII долоо хоног")
    wr("ppt/slides/slide1.xml", s)

    # 2 done work (XI, XII, XIII)
    s = rd("ppt/slides/slide2.xml")
    s = set_paras(s, "Badge text X", ["XI"])
    s = set_paras(s, "Task X", ["UCS & A* үндсэн тестүүд"])
    s = set_paras(s, "File X", ["search.py · бүх тест давсан"])
    s = set_paras(s, "Badge text XI", ["XII"])
    s = set_paras(s, "Task XI", ["Ажилдаг хайлтын prototype, явцийн pdf"])
    s = set_paras(s, "File XI", ["app.py · progress_week12.pdf"])
    s = set_paras(s, "Badge text XII", ["XIII"])
    s = set_paras(s, "Task XII", ["Байесийн сүлжээ: цаг агаар, цаг → түгжрэл"])
    s = set_paras(s, "File XII", ["traffic.py · app.py --weather --time · scale_test.py"])
    wr("ppt/slides/slide2.xml", s)

    # 3 Bayesian network: variables
    s = rd("ppt/slides/slide3.xml")
    s = s.replace("<a:t>ЗАМЫН ГРАФ</a:t>", "<a:t>БАЙЕСИЙН СҮЛЖЭЭ</a:t>")
    ps, pe = s.index("<p:pic>"), s.index("</p:pic>") + len("</p:pic>")
    s = s[:ps] + bn_diagram() + s[pe:]
    s = set_paras(s, "Stat 0", ["3"])
    s = set_paras(s, "Stat label 0", ["хувьсагч"])
    s = set_paras(s, "Stat 1", [str(len(traffic.CPD_CONG))])
    s = set_paras(s, "Stat label 1", ["CPD мөр, нийлбэр = 1"])
    s = set_paras(s, "Stat 2", ["0"])
    s = set_paras(s, "Stat label 2", ["шинэ сан (цэвэр Python)"])
    wr("ppt/slides/slide3.xml", s)
    rels = rd("ppt/slides/_rels/slide3.xml.rels")
    rels = re.sub(r'<Relationship Id="rId1"[^>]*image-3-1.png"/>', "", rels)
    wr("ppt/slides/_rels/slide3.xml.rels", rels)
    os.remove(os.path.join(tmp, "ppt/media/image-3-1.png"))

    # 4 CPD example + edge weight
    s = rd("ppt/slides/slide4.xml")
    s = set_paras(s, "Text 0", ["CPD ЖИШЭЭ, ИРМЭГИЙН ЖИН"])
    s = set_paras(s, "UCS title", ["CPD мөр: цас + өглөө"])
    s = set_paras(s, "UCS text", [f"P(бага, дунд, их | цас, өглөөний оргил) = {p[0]:.2f}, {p[1]:.2f}, {p[2]:.2f}",
                                  f"{len(traffic.CPD_CONG)} мөр бүгд нийлбэр 1 (тест)",
                                  "Тоо нь таамаг: УБ-ын уур амьсгал, оргил цагийн урт"])
    s = set_paras(s, "A* title", ["Ирмэг бүрийн E[түгжрэл]"])
    s = set_paras(s, "A* text", ["Δ: бага −0.25 · дунд 0 · их +0.25",
                                 f"Энхтайваны өргөн чөлөө N01→N02: {c0:.2f} → {c1:.2f}, {t0:.2f} → {t1:.2f} мин",
                                 "Хурд ≤ 70 км/ц тул h admissible, UCS/A* оновчтой"])
    s = set_paras(s, "Travel time formula", ["Хугацаа = зай ÷ ( хурд × (1 − 0.7 × E[түгжрэл]) )"])
    wr("ppt/slides/slide4.xml", s)

    # 5 results (+ chart)
    s = rd("ppt/slides/slide5.xml")
    s = set_paras(s, "Optimal count", [f"{pairs}/{pairs}"])
    s = set_paras(s, "Optimal label", [f"хос × {nconds} нөхцөлд UCS, A* ижил оновчтой өртөг"])
    s = set_paras(s, "Saving", [pct(big)])
    s = set_paras(s, "Saving label", ["A*-ийн хэмнэлт, 64 зангилаа: хугацаа / зай"])
    wr("ppt/slides/slide5.xml", s)
    ch = rd("ppt/charts/chart1.xml")
    ch = ch.replace("<a:t>Дундаж шалгасан зангилаа</a:t>",
                    "<a:t>Дундаж шалгасан зангилаа (64 зангилаа)</a:t>")
    vals = [big["ucs_nodes_time"], big["ucs_nodes_dist"], big["astar_nodes_time"], big["astar_nodes_dist"]]
    it = iter(vals)
    ch = re.sub(r'(<c:pt idx="[01]"><c:v>)([\d.]+)(</c:v></c:pt>)', lambda m: f"{m.group(1)}{next(it)}{m.group(3)}", ch)
    ch = ch.replace('<c:max val="10"/>', '<c:max val="35"/>')
    wr("ppt/charts/chart1.xml", ch)
    # keep the embedded workbook in sync with the chart cache
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

    # 6 demo with real output
    s = rd("ppt/slides/slide6.xml")
    s = s.replace("<a:t>PROTOTYPE: app.py</a:t>", "<a:t>DEMO: app.py --weather --time</a:t>")
    stops = route.split(" -> ")
    s = set_paras(s, "Terminal text", [
        ("$ python3 app.py --from N01 --to N15 \\", 0),
        ("    --compare --weather snow --time morning peak", 0),
        (f"[Bayes] P(low/med/high) = {'/'.join(bayes)}", 2),
        (f"[UCS]  {costs[0][0]} min | {costs[0][1]} nodes", 2),
        (f"[A*]   {costs[1][0]} min | {costs[1][1]} nodes", 3),
        (" ", 1),
        (f"{stops[0]} ->", 5),
        ("  " + " -> ".join(stops[1:3]) + " ->", 6),
        ("  " + " -> ".join(stops[3:]), 7),
        (" ", 8),
        (f"Same optimal cost: {'yes' if 'Same optimal cost: yes' in n['demo_out'] else 'NO'}", 9),
        (f"(--weather/--time-гүй: {dcosts[0][0]} min)", 5),
    ], size=1200)
    s = set_paras(s, "Options title", ["Шинэ сонголтууд"])
    s = set_paras(s, "Options list", ["--weather clear | snow | rain",
                                      "--time off-peak | morning peak | evening peak",
                                      "Нэгийг нь өгвөл нөгөөг prior-оор нэгтгэнэ",
                                      "Аль нь ч өгөөгүй бол XII-ын гаралт яг хэвээр",
                                      "64 зангилаат граф: --data data_scale"])
    wr("ppt/slides/slide6.xml", s)

    # 7 next steps
    s = rd("ppt/slides/slide7.xml")
    s = set_paras(s, "Next title", ["XIV долоо хоног"])
    s = set_paras(s, "Next list", ["experiments.py: 30 хос × 4 нөхцөл × 10 давталт",
                                   "Зайн маршрут ба түгжрэл тооцсон маршрут",
                                   "Гар тооцоо, BN, түүвэрлэлтийн зөрүү",
                                   "Замын ангиллаар өөр CPD"])
    s = set_paras(s, "Risk list", ["CPD-ийн тоо таамаг: бодит хэмжилтээр шалгах",
                                   f"Нөхцөл бүх замд адил нөлөөлдөг: маршрут ≤{n['route_changes']}/{pairs} хосод л өөрчлөгдсөн",
                                   "OSM өгөгдөл дээр хараахан туршаагүй"])
    wr("ppt/slides/slide7.xml", s)

    # speaker notes
    notes = {
        1: "Нээлт: төслийн нэр, XIII долоо хоногийн явцийн тайлан.",
        2: "XI, XII, XIII долоо хоногийн ажил бүгд дууссан.",
        3: "Цаг агаар ба өдрийн цаг нь түгжрэлийн түвшинд нөлөөлнө. Бүх магадлал синтетик таамаг.",
        4: "Хот даяарх түвшин замын өөрийн түгжрэлийг ±0.25-аар шилжүүлнэ; хүлээгдэх утгыг ирмэгийн жинд ашиглана.",
        5: f"{pairs} хос, {nconds} нөхцөл бүрт UCS = A*. 64 зангилаатай граф дээр {pct(big)}; 15 зангилаатай граф дээр {pct(city)} (XII-тай ижил).",
        6: "Terminal дээр шууд ажиллуулж үзүүлнэ.",
    }
    for i, t in notes.items():
        path = f"ppt/notesSlides/notesSlide{i}.xml"
        x = rd(path)
        x = re.sub(r"<a:t>[^<]*[^\d<][^<]*</a:t>", f"<a:t>{escape(t)}</a:t>", x, count=1)
        wr(path, x)

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
    big = n["scale"][("scale (64 nodes)", "default")]
    print(f"traffic.py: {n['traffic_pass']} PASS; {len(n['pair_checks'])} conditions x {n['pair_checks'][0][0]} pairs, 0 mismatches")
    print(f"64-node graph: UCS {big['ucs_nodes_time']}/{big['ucs_nodes_dist']}  A* {big['astar_nodes_time']}/{big['astar_nodes_dist']}  "
          f"-> -{round(big['reduction_time_pct'])}% / -{round(big['reduction_dist_pct'])}%")
    print("demo:", parse_compare(n["demo_out"])[0], "default:", parse_compare(n["default_out"])[0])
    print(f"wrote {OUT_PPTX} and {OUT_PDF}")


if __name__ == "__main__":
    main()
