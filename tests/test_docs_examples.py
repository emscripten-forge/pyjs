"""The JavaScript examples of the docs (docs/JavaScript_API.md, index.md,
README.md) still work: each runs here as JavaScript against the runtime of
the test page (`globalThis.pyjs`, set by the test harness)."""

import pytest

from pyjs.code import run_js


def js(body):
    """run `body` as a JavaScript function body with `pyjs` in scope"""
    return run_js(f"(function () {{ const pyjs = globalThis.pyjs; {body} }})")()


def test_run_python():
    assert js('return pyjs.runPython("x = 20\\nx + 1");') == 21


def test_quickstart_list():
    assert js(
        """
        const py_list = pyjs.runPython("[i * i for i in range(10)]");
        const value = py_list.get(3);
        py_list.destroy();
        return value;
        """
    ) == 9


def test_pyimport():
    assert js(
        """
        const math = pyjs.pyimport("math");
        const value = math.sqrt(2);
        math.destroy();
        return value;
        """
    ) == pytest.approx(2**0.5)


def test_globals():
    assert js(
        """
        pyjs.globals.set("n_docs_example", 7);
        const value = pyjs.runPython("n_docs_example * 6");
        pyjs.globals.delete("n_docs_example");
        return value;
        """
    ) == 42


def test_to_py():
    assert js(
        """
        const d = pyjs.toPy({ a: [1, 2, 3] });
        pyjs.globals.set("d_docs_example", d);
        const value = pyjs.runPython("sum(d_docs_example['a'])");
        pyjs.globals.delete("d_docs_example");
        d.destroy();
        return value;
        """
    ) == 6


def test_python_error():
    assert js(
        """
        try {
          pyjs.runPython("{}['missing']");
        } catch (e) {
          return [e instanceof pyjs.PythonError, e.type].join(" ");
        }
        """
    ) == "true KeyError"


def test_numpy_proxy():
    pytest.importorskip("numpy")
    assert js(
        """
        const arr = pyjs.runPython("import numpy\\nnumpy.eye(2)");
        const result = [arr.shape.toString(), arr.get(0).get(0), JSON.stringify(arr.tolist().toJs())];
        arr.destroy();
        return result.join(" | ");
        """
    ) == "(2, 2) | 1 | [[1,0],[0,1]]"
