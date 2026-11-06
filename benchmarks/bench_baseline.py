"""Pure python baselines: harness / interpreter overhead without any FFI."""


def _noop():
    pass


async def _anoop():
    pass


def bench_py_noop_call(benchmark):
    benchmark(_noop)


def bench_py_lambda_call(benchmark):
    # many benchmarks wrap the measured expression in a lambda
    benchmark(lambda: None)


async def bench_py_await_noop_coroutine(benchmark):
    # awaiting a coroutine that never yields to the event loop
    await benchmark.aio(_anoop)
