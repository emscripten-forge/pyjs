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
