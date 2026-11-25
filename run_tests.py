"""run_tests.py - run every test suite of the project (no pytest needed).

    python3 run_tests.py

Suites: search.py (Week XI UCS/A*), traffic.py (Week XIII Bayesian network,
hand calculations, 210-pair optimality), test_week13.py (CLI, scale graph),
test_week14.py (road-class model, experiments C and D),
test_week15.py (OSM graph, E[t], calibration).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SUITES = ["search.py", "traffic.py", "test_week13.py", "test_week14.py", "test_week15.py", "test_visualizer.py",
          "test_ub_graph.py"]


def main():
    results = []
    for s in SUITES:
        print(f"\n===== {s} =====", flush=True)
        r = subprocess.run([sys.executable, s], cwd=HERE)
        results.append((s, r.returncode == 0))
    print("\n===== summary =====")
    for s, ok in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {s}")
    good = all(ok for _, ok in results)
    print(f"\n{sum(ok for _, ok in results)}/{len(results)} suites passed")
    return good


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
