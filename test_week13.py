"""test_week13.py - Week XIII tests (same PASS/FAIL style as search.py / traffic.py).

    python3 test_week13.py       # exit code 0 = all passed
    python3 run_tests.py         # runs search.py, traffic.py and this file

Covers: no network use, existing test suites still green, app.py output with
no --weather/--time is identical to before Week XIII (fixtures/), the new
options change the result, and the 64-node scale graph keeps UCS == A*.
(If pytest is installed, `python3 -m pytest test_week13.py` also works.)
"""
import io
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Runs app.py in a child process with every socket connection disabled.
_OFFLINE_APP = (
    "import socket, runpy, sys\n"
    "def _no_net(*a, **k): raise OSError('network disabled in tests')\n"
    "socket.socket.connect = _no_net; socket.create_connection = _no_net\n"
    "sys.argv = ['app.py'] + sys.argv[1:]\n"
    "runpy.run_path('app.py', run_name='__main__')\n"
)


def app(*args):
    r = subprocess.run([sys.executable, "-c", _OFFLINE_APP, *args], cwd=HERE,
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def mask_ms(s):
    return re.sub(r"\d+\.\d+ ms", "<ms> ms", s)


def costs(out):
    return [float(x) for x in re.findall(r"Cost  : ([\d.]+)", out)]


def run_tests():
    from graph import Graph
    import search
    import traffic
    import scale_test

    ok = True

    def check(name, cond):
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {name}")
        ok &= bool(cond)

    # 0. offline: block sockets for everything that runs in this process
    def _no_net(*a, **k):
        raise OSError("network disabled in tests")
    socket.socket.connect, socket.create_connection = _no_net, _no_net
    # (this file imports socket only to block it, so it is not scanned)
    srcs = [f for f in os.listdir(HERE) if f.endswith(".py") and f != "test_week13.py"]
    net = [f for f in srcs if re.search(r"^\s*(import|from)\s+(socket|urllib|requests|http|ftplib|ssl)\b",
                                        open(os.path.join(HERE, f), encoding="utf-8").read(), re.M)]
    check(f"No network imports in {len(srcs)} project .py files; sockets blocked during tests", not net)

    # 1. existing test suites (run in-process, quietly) still pass
    for name, fn in [("search.py (Week XI)", search.run_tests), ("traffic.py (Week XIII, incl. 210-pair checks)", traffic.run_tests)]:
        buf = io.StringIO()
        cwd = os.getcwd()
        os.chdir(HERE)
        try:
            with redirect_stdout(buf):
                res = fn()
        finally:
            os.chdir(cwd)
        fails = [l for l in buf.getvalue().splitlines() if l.startswith("[FAIL]")]
        check(f"{name} run_tests() all green ({buf.getvalue().count('[PASS]')} PASS)", res and not fails)

    # 2. app.py without --weather/--time: identical to the pre-Week-XIII output
    #    (fixtures recorded from the Week XII code; only the timing in ms is masked)
    fx = json.load(open(os.path.join(HERE, "fixtures", "app_output_before_week13.json"), encoding="utf-8"))
    diff = [cmd for cmd, want in fx.items() if mask_ms(app(*cmd.split())[1]) != want]
    check(f"app.py default output identical to before on {len(fx)} commands (differ: {diff or 'none'})", not diff)

    # 3. app.py with the Bayesian inputs ("morning peak" may be two words)
    rc0, base, _ = app("--from", "N01", "--to", "N15", "--compare")
    rc1, snow, _ = app("--from", "N01", "--to", "N15", "--compare", "--weather", "snow", "--time", "morning", "peak")
    c0, c1 = costs(base), costs(snow)
    check(f"--weather snow --time morning peak runs and changes the cost ({c0[:1]} -> {c1[:1]} min)",
          rc0 == 0 and rc1 == 0 and "[Bayes] weather=snow, time=morning_peak" in snow
          and len(c1) == 2 and c1[0] == c1[1] and c1[0] > c0[0] and "Same optimal cost: yes" in snow)
    _, off, _ = app("--from", "N01", "--to", "N15", "--weather", "clear", "--time", "off-peak")
    check(f"clear + off-peak is faster than snow + morning peak ({costs(off)[:1]} < {c1[:1]})",
          costs(off) and costs(off)[0] < c1[0])
    rc, _, err = app("--from", "N01", "--to", "N15", "--weather", "hail")
    check("Unknown --weather value is rejected with a usage error", rc == 2 and "hail" in err)

    # 4. the --compare result equals the library result on the conditioned graph
    g = Graph().load(os.path.join(HERE, "nodes.csv"), os.path.join(HERE, "edges.csv"))
    _, c_lib, _ = search.astar(traffic.apply_conditions(g, "snow", "morning_peak"), "N01", "N15")
    check(f"CLI cost matches apply_conditions + astar ({c_lib:.2f} min)", abs(c_lib - c1[0]) < 0.005)

    # 5. scale test: generated graph (>= 50 nodes), deterministic, UCS == A* on all pairs
    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        scale_test.generate(d1)
        scale_test.generate(d2)
        same = all(open(f"{d1}/{f}").read() == open(f"{d2}/{f}").read() for f in ("nodes.csv", "edges.csv"))
        gs = Graph().load(f"{d1}/nodes.csv", f"{d1}/edges.csv")
    check(f"Scale graph has {len(gs.nodes)} nodes / {len(gs.edges)} directed edges, generated deterministically",
          len(gs.nodes) >= 50 and same and all(e["speed_kmh"] <= 70 for e in gs.edges))
    for w, t in [(None, None), ("clear", "off_peak"), ("snow", "morning_peak"), ("rain", "evening_peak")]:
        gc = gs if w is None else traffic.apply_conditions(gs, w, t)
        slack = min(e["time_min"] - gc.heuristic_time_min(e["src"], e["dst"]) for e in gc.edges)
        m = scale_test.measure(gc)
        check(f"Scale {w or 'default'}+{t or '-'}: UCS == A* on {m['pairs']} pairs x time/dist, "
              f"A* -{m['time']['reduction']:.0f}% / -{m['dist']['reduction']:.0f}% nodes",
              m["time"]["mismatches"] == 0 and m["dist"]["mismatches"] == 0 and slack >= 0
              and m["time"]["astar"] < m["time"]["ucs"] and m["dist"]["astar"] < m["dist"]["ucs"])

    print("\nALL TESTS PASSED" if ok else "\nSOME TESTS FAILED")
    return ok


# ---- pytest entry points (pytest is optional: `python3 -m pytest -v`) ----
def _in_project(fn):
    cwd = os.getcwd()
    os.chdir(HERE)
    try:
        return fn()
    finally:
        os.chdir(cwd)


def test_search_suite():
    """Week XI: search.py tests (UCS/A* on all pairs, one-way, blocked road)."""
    import search
    assert _in_project(search.run_tests)


def test_traffic_suite():
    """Week XIII: CPD rows, hand calculations, 210-pair optimality x 12 conditions."""
    import traffic
    assert _in_project(traffic.run_tests)


def test_week13():
    """Week XIII: offline, CLI unchanged by default, --weather/--time, scale graph."""
    assert _in_project(run_tests)


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)
