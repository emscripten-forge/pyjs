import pytest
import pyjs

from .conftest import *


class TestPyToJs:
    @pytest.mark.parametrize(
        "test_input",
        [-1, 1, 1.0, 0, True, False, "0"],
    )
    def test_fundamentals(self, test_input):
        output = pyjs.to_js(test_input)
        assert js_assert_eq(output, pyjs.JsValue(test_input))

    def test_none(self):
        t = pyjs.to_js(None)
        assert pyjs.pyjs_core._module._is_undefined(t) == True


class TestPyToJsDict:
    def test_dict_size_key(self):
        # regression: a dict key named "size" used to collide with
        # Map.prototype.size (the entry count getter) in the LiteralMap get trap.
        d = pyjs.to_js({"size": 7})
        assert pyjs.to_py(d["size"]) == 7

    def test_dict_int_values(self):
        d = pyjs.to_js({"size": 32, "usage": 136, "zero": 0, "one": 1})
        assert pyjs.to_py(d["size"]) == 32
        assert pyjs.to_py(d["usage"]) == 136
        assert pyjs.to_py(d["zero"]) == 0
        assert pyjs.to_py(d["one"]) == 1

    def test_dict_roundtrip(self):
        x = {"size": 32, "label": "hello", "flag": True}
        d = pyjs.to_js(x)
        assert pyjs.to_py(d["size"]) == 32
        assert pyjs.to_py(d["label"]) == "hello"
        assert pyjs.to_py(d["flag"]) is True
