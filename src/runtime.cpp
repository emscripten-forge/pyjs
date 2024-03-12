#include <pybind11/embed.h>
#include <emscripten/bind.h>
#include <pyjs/export_pyjs_module.hpp>
#include <pyjs/export_js_module.hpp>

PYBIND11_EMBEDDED_MODULE(pyjs_core, m)
{
    pyjs::export_pyjs_module(m);
}

EMSCRIPTEN_BINDINGS(my_module)
{
    pyjs::export_js_module();
}
