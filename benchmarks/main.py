"""Entry point for running the pyjs benchmarks in the browser.

Run via ``pyjs_code_runner run script ... --script main.py --async-main``
(see ``build_local.sh --bench``).

Discovers ``bench_*`` functions (sync or async) in ``bench_*.py`` modules next
to this file, runs them with the async-aware harness, prints a table and a
single machine readable line::

    PYJS_BENCH_RESULT_JSON: {...}

which the host side extracts from the captured output (files written in the
browser file system are not visible on the host).

An optional ``/bench_config/config.json`` may contain::

    {"filter": "substring", "min_round_time": 0.05, "rounds": 5}
"""

import importlib
import inspect
import json
import os
import sys
import time
import traceback

BENCH_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, BENCH_DIR)

import pyjs  # noqa: E402
from harness import format_table, run_benchmark_function  # noqa: E402

RESULT_MARKER = "PYJS_BENCH_RESULT_JSON:"
CONFIG_PATH = "/bench_config/config.json"


def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}


def discover(name_filter=None):
    benches = []
    for fname in sorted(os.listdir(BENCH_DIR)):
        if not (fname.startswith("bench_") and fname.endswith(".py")):
            continue
        mod_name = fname[:-3]
        module = importlib.import_module(mod_name)
        # keep definition order within a module
        for name, obj in vars(module).items():
            if name.startswith("bench_") and inspect.isfunction(obj):
                full_name = f"{mod_name[len('bench_'):]}::{name[len('bench_'):]}"
                if name_filter and name_filter not in full_name:
                    continue
                benches.append((full_name, obj))
    return benches


def environment_info():
    info = dict(
        python=sys.version,
        platform=sys.platform,
        pointer_bits=64 if sys.maxsize > 2**32 else 32,
    )
    try:
        info["user_agent"] = str(pyjs.js.navigator.userAgent)
    except Exception:
        pass
    return info


async def main():
    config = load_config()
    harness_kwargs = {
        k: config[k] for k in ("min_round_time", "rounds") if k in config
    }
    benches = discover(config.get("filter"))

    bar = "=" * 40
    print(f"{bar}\nRUN BENCHMARKS ({len(benches)}):\n{bar}")

    results = []
    n_failed = 0
    t0 = time.perf_counter()
    for name, fn in benches:
        print(f"BENCH: {name}", flush=True)
        try:
            results.append(await run_benchmark_function(name, fn, **harness_kwargs))
        except Exception as e:
            traceback.print_exc()
            results.append(dict(name=name, error=f"{type(e).__name__}: {e}"))
            n_failed += 1
    total = time.perf_counter() - t0

    print()
    print(format_table(results))
    print(f"\n{len(results) - n_failed} benchmarks ok, {n_failed} failed in {total:.1f}s")

    payload = dict(environment=environment_info(), config=config, results=results)
    print(RESULT_MARKER + " " + json.dumps(payload), flush=True)

    return 1 if n_failed else 0
