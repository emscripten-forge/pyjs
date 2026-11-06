"""Python -> JavaScript: attribute access and calling JS functions from python."""

import pyjs
from pyjs import js

_f_noargs = js.Function("return 1")
_f_identity = js.Function("a", "return a")
_f_three = js.Function("a", "b", "c", "return a")
_f_ret_str = js.Function("return 'hello world'")
_f_ret_obj = js.Function("return {}")


def bench_js_module_getattr(benchmark):
    # pyjs.js.<name> goes through the module __getattr__
    benchmark(lambda: js.Math)


def bench_jsvalue_getattr(benchmark):
    math = js.Math
    benchmark(lambda: math.PI)


def bench_jsvalue_setattr(benchmark):
    obj = pyjs.new(js.Object)
    benchmark(lambda: setattr(obj, "x", 1))


def bench_jsvalue_getitem(benchmark):
    arr = js.Function("return [1,2,3]")()
    benchmark(lambda: arr[1])


def bench_call_noargs(benchmark):
    benchmark(_f_noargs)


def bench_call_int_arg(benchmark):
    benchmark(_f_identity, 1)


def bench_call_float_arg(benchmark):
    benchmark(_f_identity, 1.5)


def bench_call_3_args(benchmark):
    benchmark(_f_three, 1, 2, 3)


def bench_call_short_str_arg(benchmark):
    benchmark(_f_identity, "hello")


def bench_call_10kb_str_arg(benchmark):
    s = "x" * 10_000
    benchmark(_f_identity, s)


def bench_call_returns_str(benchmark):
    benchmark(_f_ret_str)


def bench_call_returns_object(benchmark):
    benchmark(_f_ret_obj)


def bench_call_method(benchmark):
    math = js.Math
    benchmark(lambda: math.max(1, 2))


def bench_new_object(benchmark):
    cls = js.Object
    benchmark(pyjs.new, cls)


def bench_function_creation(benchmark):
    benchmark(js.Function, "a", "return a")
