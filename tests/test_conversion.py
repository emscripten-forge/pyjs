import pytest
import pyjs

from helpers import *


class TestPyToJs:
    @pytest.mark.parametrize(
        "test_input",
        [-1, 1, 1.0, 0, True, False, "0"],
    )
    def test_fundamentals(self, test_input):
        output = pyjs.to_js(test_input)
        # (values that are converted automatically pass through to_js unchanged)
        assert js_assert_eq(output, test_input)

    def test_none(self):
        t = pyjs.to_js(None)
        assert pyjs.pyjs_core._module._is_undefined(t) == True

    @pytest.mark.parametrize(
        "keys",
        [
            (1, "1"),
            (1.0, "1"),
            (1.5, "1.5"),
            (True, "true"),
            # floats JavaScript names differently than Python
            (float("inf"), "Infinity"),
            (float("-inf"), "-Infinity"),
            (float("nan"), "NaN"),
            (1e21, "1e+21"),
            (1e-7, "1e-7"),
        ],
    )
    def test_dict_key_collision(self, keys):
        """two keys that become the same JavaScript property: an error, not
        a silently lost value"""
        with pytest.raises(pyjs.ConversionError):
            pyjs.to_js(dict.fromkeys(keys, 0))

    def test_c_long_buffer(self):
        """a buffer of C longs (format "l": 32 bit on wasm32, 64 bit on
        wasm64, numpy's int64 there): the typed array has the right item
        size, through to_js and buffer_to_js"""
        import array
        import struct

        longs = array.array("l", [1, -2, 3])
        expected_class = "Int32Array" if struct.calcsize("l") == 4 else "BigInt64Array"
        for js_array in [pyjs.to_js(longs), pyjs.buffer_to_js_typed_array(longs)]:
            assert js_array.constructor.name == expected_class
            assert [int(x) for x in js_array] == [1, -2, 3]

    def test_dict_float_keys_without_collision(self):
        """float keys become the property names JavaScript gives them"""
        obj = pyjs.to_js({float("inf"): 1, 1e21: 2, 0.5: 3})
        assert pyjs.to_py(pyjs.js.Object.keys(obj)) == ["Infinity", "1e+21", "0.5"]

    def test_only_lists_and_tuples_become_arrays(self):
        # as in pyodide: other sequences (range, deque, ...) are not copied,
        # JavaScript gets a proxy of them
        import collections

        is_array = pyjs.js.Array.isArray
        assert is_array(pyjs.to_js([1, 2]))
        assert is_array(pyjs.to_js((1, 2)))
        for sequence in [range(3), collections.deque([1, 2])]:
            # (an object that is not converted comes back as a proxy of it,
            # a JSDoubleProxy)
            result = pyjs.to_js(sequence)
            assert isinstance(result, pyjs.ffi.JSDoubleProxy)
            assert not is_array(result)
            assert result.unwrap() is sequence
        # a range far too big to copy: no attempt to copy it
        huge = range(2**31)
        assert pyjs.to_js(huge).unwrap() is huge
        # inside a converted container: stored as proxy, read back as itself
        inner = range(2)
        array = pyjs.to_js([inner])
        assert is_array(array)
        assert not is_array(pyjs.js.Function("a", "return a[0];")(array))
        assert array[0] is inner
