"""Minimal async-aware benchmark harness for pyjs.

pytest-benchmark cannot be used in the browser: pytest runs synchronously, and
async code (``await asyncio.sleep(0)``, awaiting JS promises, ...) can only
make progress when control is handed back to the browser event loop. This
harness is driven from an ``async def main()`` and therefore can ``await``.

API (modelled after pytest-benchmark)::

    def bench_something(benchmark):
        f = setup()
        benchmark(f, arg0, arg1)            # sync

    async def bench_something_async(benchmark):
        await benchmark.aio(coro_fn, arg0)  # async

    # when the measured callable performs `k` operations itself
    # (e.g. a JS loop calling into python k times), pass ops=k to get
    # per-operation timings
    benchmark(js_loop, k, ops=k)
"""

import inspect
import statistics
import time

perf_counter = time.perf_counter


class BenchmarkError(RuntimeError):
    pass


class Benchmark:
    def __init__(self, name, min_round_time=0.05, rounds=5, max_iterations=10_000_000):
        self.name = name
        self.min_round_time = min_round_time
        self.rounds = rounds
        self.max_iterations = max_iterations
        self.result = None

    # -- public api ---------------------------------------------------------
    def __call__(self, fn, *args, ops=1):
        self._check_unused()

        def run(n):
            t0 = perf_counter()
            for _ in range(n):
                fn(*args)
            return perf_counter() - t0

        n = self._calibrate_sync(run)
        times = [run(n) for _ in range(self.rounds)]
        self._store(times, n, ops)

    async def aio(self, coro_fn, *args, ops=1):
        self._check_unused()

        async def run(n):
            t0 = perf_counter()
            for _ in range(n):
                await coro_fn(*args)
            return perf_counter() - t0

        n = 1
        while True:
            t = await run(n)
            n_next = self._next_n(n, t)
            if n_next is None:
                break
            n = n_next
        times = [await run(n) for _ in range(self.rounds)]
        self._store(times, n, ops)

    # -- internals ----------------------------------------------------------
    def _check_unused(self):
        if self.result is not None:
            raise BenchmarkError(f"{self.name}: benchmark fixture used more than once")

    def _next_n(self, n, t):
        """Return the next iteration count, or None if `n` is good enough."""
        if t >= self.min_round_time or n >= self.max_iterations:
            return None
        if t <= 0:
            return n * 10
        # aim slightly above the target to avoid many calibration steps
        target = int(n * self.min_round_time * 1.2 / t) + 1
        return min(max(target, n * 2), self.max_iterations)

    def _calibrate_sync(self, run):
        n = 1
        while True:
            t = run(n)
            n_next = self._next_n(n, t)
            if n_next is None:
                return n
            n = n_next

    def _store(self, times, n, ops):
        per_op = [t / (n * ops) for t in times]
        median = statistics.median(per_op)
        self.result = dict(
            name=self.name,
            iterations=n,
            ops_per_iteration=ops,
            rounds=len(times),
            min=min(per_op),
            max=max(per_op),
            mean=statistics.fmean(per_op),
            median=median,
            stddev=statistics.stdev(per_op) if len(per_op) > 1 else 0.0,
            ops_per_sec=(1.0 / median) if median > 0 else float("inf"),
        )


async def run_benchmark_function(name, fn, **benchmark_kwargs):
    benchmark = Benchmark(name, **benchmark_kwargs)
    ret = fn(benchmark)
    if inspect.isawaitable(ret):
        await ret
    if benchmark.result is None:
        raise BenchmarkError(f"{name}: benchmark fixture was never called")
    return benchmark.result


def format_time(seconds):
    for unit, scale in (("s", 1.0), ("ms", 1e-3), ("us", 1e-6), ("ns", 1e-9)):
        if seconds >= scale:
            return f"{seconds / scale:8.3f} {unit}"
    return f"{seconds / 1e-9:8.3f} ns"


def format_table(results):
    name_w = max([len("name")] + [len(r["name"]) for r in results])
    header = (
        f"{'name':<{name_w}}  {'median/op':>11}  {'min/op':>11}  "
        f"{'mean/op':>11}  {'stddev':>11}  {'ops/s':>12}  {'iters x rounds':>15}"
    )
    lines = [header, "-" * len(header)]
    for r in results:
        if "error" in r:
            lines.append(f"{r['name']:<{name_w}}  ERROR: {r['error']}")
            continue
        lines.append(
            f"{r['name']:<{name_w}}  {format_time(r['median']):>11}  "
            f"{format_time(r['min']):>11}  {format_time(r['mean']):>11}  "
            f"{format_time(r['stddev']):>11}  {r['ops_per_sec']:12.1f}  "
            f"{r['iterations'] * r['ops_per_iteration']:>8} x {r['rounds']:<4}"
        )
    return "\n".join(lines)
