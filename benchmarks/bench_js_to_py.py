"""JavaScript -> Python: JS code calling python callables.

The calls are issued from a JS loop (N calls per measured iteration), so the
reported per-op time is the cost of a single JS -> python call.
"""

from compat import create_once_callable, create_proxy, js

N = 1000

_loop_noargs = js.Function("f", "n", "for (let i = 0; i < n; i++) { f(); }")
_loop_int = js.Function("f", "n", "let s = 0; for (let i = 0; i < n; i++) { s += f(i); } return s;")
_loop_str = js.Function("f", "n", "for (let i = 0; i < n; i++) { f('hello'); }")
_loop_obj = js.Function("f", "n", "const o = {a: 1}; for (let i = 0; i < n; i++) { f(o); }")


def _bench_loop(benchmark, js_loop, py_function):
    """measure `js_loop` calling `py_function` N times"""
    callback = create_proxy(py_function)
    try:
        benchmark(js_loop, callback, N, ops=N)
    finally:
        callback.destroy()


def bench_js_calls_py_noargs(benchmark):
    _bench_loop(benchmark, _loop_noargs, lambda: None)


def bench_js_calls_py_int_roundtrip(benchmark):
    _bench_loop(benchmark, _loop_int, lambda i: i)


def bench_js_calls_py_str_arg(benchmark):
    _bench_loop(benchmark, _loop_str, lambda s: None)


def bench_js_calls_py_object_arg(benchmark):
    _bench_loop(benchmark, _loop_obj, lambda o: None)


# (the names are kept so that results stay comparable with older runs)
def bench_create_and_delete_callable(benchmark):
    def f():
        pass

    def create_destroy():
        create_proxy(f).destroy()

    benchmark(create_destroy)


def bench_create_once_callable_and_call(benchmark):
    def f():
        pass

    def create_call():
        create_once_callable(f)()

    benchmark(create_call)
