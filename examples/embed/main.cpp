// A C++ program with python and pyjs in it: pyjs starts python, python code
// run with pybind11 uses numpy (shared libraries, loaded at the import) and
// calls JavaScript through pyjs. Everything is set up from C++, the program
// needs no JavaScript of its own:
//
//     node build/wasm32/embed.js
//
// The python environment (standard library, numpy, the package pyjs) is in
// the file system already when main runs, under the prefix EMBED_PYTHON_HOME
// ("/python"): emscripten's file packager put it there (see CMakeLists.txt).
#include <pybind11/eval.h>
#include <pyjs/pyjs.h>

#include <cstdio>
#include <cstdlib>
#include <string>

namespace py = pybind11;

int main()
{
    // python + pyjs, python's prefix is EMBED_PYTHON_HOME. pybind11 works in
    // this interpreter, it does not need to start it itself (no
    // py::scoped_interpreter: that would also finalize python when main
    // returns, but python lives on, JavaScript events call into it later)
    if (pyjs_initialize(EMBED_PYTHON_HOME) != 0)
    {
        std::exit(1);
    }

    // python code using numpy (its extension modules are shared libraries,
    // loaded by `import numpy`) and pyjs (`pyjs.js` is JavaScript's
    // globalThis): numpy computes, JavaScript's Math.sqrt checks it
    std::string text;
    double norm = 0, js_norm = 0;
    try
    {
        py::exec(R"(
import numpy as np
import pyjs

a = np.arange(1, 5, dtype=np.float64)          # [1. 2. 3. 4.]
norm = float(np.linalg.norm(a))                # numpy (openblas)
js_norm = pyjs.js.Math.sqrt(float(a @ a))      # JavaScript
text = f"numpy {np.__version__}: |{a}| = {norm:.6f}, JavaScript's Math.sqrt: {js_norm:.6f}"
)");
        text = py::globals()["text"].cast<std::string>();
        norm = py::globals()["norm"].cast<double>();
        js_norm = py::globals()["js_norm"].cast<double>();
    }
    catch (const py::error_already_set& error)
    {
        // a python exception, with its traceback
        std::fprintf(stderr, "python error:\n%s\n", error.what());
        std::exit(1);
    }
    std::printf("%s\n", text.c_str());

    // (checked here: the CI runs this program; exit, not return: python
    // keeps the runtime alive, a return value would be lost)
    if (norm != js_norm || norm < 5.477 || norm > 5.478)
    {
        std::fprintf(stderr, "FAILED: expected sqrt(30) from numpy and JavaScript\n");
        std::exit(1);
    }
    return 0;
}
