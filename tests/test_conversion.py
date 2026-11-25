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
