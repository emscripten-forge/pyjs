"""Deep conversion: pyjs.to_js (python -> js) and pyjs.to_py (js -> python)."""

import pyjs
from pyjs import js

try:
    import numpy

    has_numpy = True
except ImportError:
    has_numpy = False

_list_100 = list(range(100))
_dict_100 = {f"key{i}": i for i in range(100)}
_nested = {"a": [1, 2, {"b": [3, 4, 5], "c": "str"}], "d": {"e": {"f": [6.5, 7.5]}}}

_js_array_100 = js.Function("return Array.from({length: 100}, (_, i) => i)")()
_js_object_100 = js.Function(
    "const o = {}; for (let i = 0; i < 100; i++) { o['key' + i] = i; } return o;"
)()
_js_map_100 = js.Function(
    "const m = new Map(); for (let i = 0; i < 100; i++) { m.set('key' + i, i); } return m;"
)()
_js_nested = js.Function(
    "return {a: [1, 2, {b: [3, 4, 5], c: 'str'}], d: {e: {f: [6.5, 7.5]}}}"
)()
_js_f64_1mb = js.Function("return new Float64Array(131072)")()


def bench_to_js_list_100_int(benchmark):
    benchmark(pyjs.to_js, _list_100)


def bench_to_js_dict_100(benchmark):
    benchmark(pyjs.to_js, _dict_100)


def bench_to_js_nested(benchmark):
    benchmark(pyjs.to_js, _nested)


def bench_to_py_array_100_int(benchmark):
    benchmark(pyjs.to_py, _js_array_100)


def bench_to_py_object_100(benchmark):
    benchmark(pyjs.to_py, _js_object_100)


def bench_to_py_map_100(benchmark):
    benchmark(pyjs.to_py, _js_map_100)


def bench_to_py_nested(benchmark):
    benchmark(pyjs.to_py, _js_nested)


def bench_to_py_float64array_1mb(benchmark):
    benchmark(pyjs.to_py, _js_f64_1mb)


if has_numpy:
    _np_f64_1mb = numpy.zeros(131072, dtype="float64")

    def bench_numpy_1mb_to_typed_array_copy(benchmark):
        benchmark(pyjs.buffer_to_js_typed_array, _np_f64_1mb)

    def bench_numpy_1mb_to_typed_array_view(benchmark):
        benchmark(lambda: pyjs.buffer_to_js_typed_array(_np_f64_1mb, view=True))
