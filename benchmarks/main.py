"""The pyjs benchmarks, run inside the browser.

The test driver (`pyjs_test_driver run ... --entry benchmarks`, see
`pixi run bench <wasm>`) writes this directory into the emscripten file
system and awaits `main(options)`. Discovers ``bench_*`` functions (sync or
async) in ``bench_*.py`` modules next to this file, runs them with the
async-aware harness, prints a table and returns the results (the driver
writes them as json on the host).

options: ``filter`` (substring of "module::name"), ``min_round_time``,
``rounds``.
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

from harness import Skip, format_table, run_benchmark_function  # noqa: E402

def discover(name_filter=None):
    """all bench_* functions of the bench_*.py modules, optionally filtered"""
    benches = []
    for fname in sorted(os.listdir(BENCH_DIR)):
        if not (fname.startswith("bench_") and fname.endswith(".py")):
            continue
        mod_name = fname[:-3]
        try:
            module = importlib.import_module(mod_name)
        except ImportError as e:
            # (a module raises it when the runtime lacks what it measures)
            print(f"SKIP: {mod_name}: {e}")
            continue
        # keep definition order within a module
        for name, obj in vars(module).items():
            if name.startswith("bench_") and inspect.isfunction(obj):
                full_name = f"{mod_name[len('bench_'):]}::{name[len('bench_'):]}"
                if name_filter and name_filter not in full_name:
                    continue
                benches.append((full_name, obj))
    return benches


def environment_info():
    """where the benchmarks ran (runtime, python, pointer size, browser)"""
    import compat

    info = dict(
        runtime=compat.RUNTIME,
        python=sys.version,
        platform=sys.platform,
        pointer_bits=64 if sys.maxsize > 2**32 else 32,
    )
    try:
        info["user_agent"] = str(compat.js.navigator.userAgent)
    except Exception:
        pass
    return info


async def main(options):
    """run the benchmarks, return environment + config + results"""
    config = {k: v for k, v in options.items() if k in ("filter", "min_round_time", "rounds")}
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
        except Skip as e:
            # (cannot run here, e.g. no JSPI: neither a result nor a failure)
            results.append(dict(name=name, skipped=str(e)))
        except Exception as e:
            traceback.print_exc()
            results.append(dict(name=name, error=f"{type(e).__name__}: {e}"))
            n_failed += 1
    total = time.perf_counter() - t0

    print()
    print(format_table(results))
    n_skipped = sum("skipped" in r for r in results)
    print(
        f"\n{len(results) - n_failed - n_skipped} benchmarks ok, {n_skipped} skipped, "
        f"{n_failed} failed in {total:.1f}s"
    )

    return dict(ok=n_failed == 0, environment=environment_info(), config=config, results=results)
