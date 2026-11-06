"""JavaScript -> Python: JS code calling python callables.

The calls are issued from a JS loop (N calls per measured iteration), so the
reported per-op time is the cost of a single JS -> python call.
"""

import pyjs
from pyjs import js

N = 1000

_loop_noargs = js.Function("f", "n", "for (let i = 0; i < n; i++) { f(); }")
_loop_int = js.Function("f", "n", "let s = 0; for (let i = 0; i < n; i++) { s += f(i); } return s;")
_loop_str = js.Function("f", "n", "for (let i = 0; i < n; i++) { f('hello'); }")
_loop_obj = js.Function("f", "n", "const o = {a: 1}; for (let i = 0; i < n; i++) { f(o); }")


def bench_js_calls_py_noargs(benchmark):
    cb, handle = pyjs.create_callable(lambda: None)
    try:
        benchmark(_loop_noargs, cb, N, ops=N)
    finally:
        handle.delete()


def bench_js_calls_py_int_roundtrip(benchmark):
    cb, handle = pyjs.create_callable(lambda i: i)
    try:
        benchmark(_loop_int, cb, N, ops=N)
    finally:
        handle.delete()


def bench_js_calls_py_str_arg(benchmark):
    cb, handle = pyjs.create_callable(lambda s: None)
    try:
        benchmark(_loop_str, cb, N, ops=N)
    finally:
        handle.delete()


def bench_js_calls_py_object_arg(benchmark):
    cb, handle = pyjs.create_callable(lambda o: None)
    try:
        benchmark(_loop_obj, cb, N, ops=N)
    finally:
        handle.delete()


def bench_create_and_delete_callable(benchmark):
    def f():
        pass

    def create_delete():
        _, handle = pyjs.create_callable(f)
        handle.delete()

    benchmark(create_delete)


def bench_create_once_callable_and_call(benchmark):
    def f():
        pass

    def create_call():
        pyjs.create_once_callable(f)()

    benchmark(create_call)
