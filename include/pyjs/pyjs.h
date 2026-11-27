/*
 * pyjs in a C / C++ program. Python code can then be run with python's C API
 * or e.g. pybind11 (which works in an interpreter it did not start: do not
 * finalize it, no pybind11::scoped_interpreter):
 *
 *     #include <pybind11/eval.h>
 *     #include <pyjs/pyjs.h>
 *
 *     int main()
 *     {
 *         pyjs_initialize("/");  // starts python (prefix "/") with pyjs in it
 *         pybind11::exec("import pyjs\n"
 *                        "pyjs.js.console.log('hello from python')");
 *     }
 *
 * A program that starts python itself (its own PyConfig, ...) instead calls
 * pyjs_init() before and pyjs_bind() after starting it:
 *
 *         pyjs_init();
 *         pybind11::initialize_interpreter();   // or Py_InitializeFromConfig
 *         pyjs_bind();
 *
 * The file system must hold the python environment before python starts
 * (the standard library at /lib/pythonX.Y, the python package `pyjs` in its
 * site-packages).
 *
 * Without C / C++, JavaScript does the same: `Module.startPython()`.
 *
 * The program must be linked as emscripten main module (-sMAIN_MODULE=1).
 */
#ifndef PYJS_PYJS_H
#define PYJS_PYJS_H

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Starts python with pyjs in it (pyjs_init, python, pyjs_bind), what
 * Module.startPython() does from JavaScript.
 *
 * python_home: python's prefix in the file system, any directory (the
 * standard library is expected at <python_home>/lib/pythonX.Y); sets
 * PYTHONHOME. NULL: PYTHONHOME if the program set it, else "/".
 * Defaults unless the program set them: LANG=en_US.UTF-8,
 * PYTHONPATH=<python_home>/lib/pythonX.Y/site-packages:/usr/lib/pythonX.Y/site-packages,
 * LD_LIBRARY_PATH=<python_home>/lib (shared libraries of the packages, e.g.
 * numpy's libopenblas.so, as in a conda environment).
 *
 * 0, or -1 if that failed (the reason is printed: e.g. no standard library in
 * the file system). Calling it again does nothing (0).
 */
int pyjs_initialize(const char* python_home);

/*
 * Before python is initialized: makes `import pyjs_core` work (registers it as
 * builtin module of the interpreter, PyImport_AppendInittab) and sets up the
 * JavaScript side of pyjs. 0, or -1 if python is already initialized (too
 * late to register a builtin module) or the registration failed. Calling it
 * again does nothing (0).
 */
int pyjs_init(void);

/*
 * After python is initialized (with the GIL held): imports the python package
 * `pyjs` and creates the JavaScript API on the emscripten Module
 * (Module.runPython / runPythonAsync / pyimport / globals / toPy), and keeps
 * the runtime alive (python is called from JavaScript events from now on).
 * 0, or -1 if that failed (the error is printed to the console). Calling it
 * again does nothing (0).
 */
int pyjs_bind(void);

#ifdef __cplusplus
}
#endif

#endif /* PYJS_PYJS_H */
