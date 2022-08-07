#include <pybind11/embed.h>
#include <emscripten/bind.h>
#include <pyjs/export_pyjs_module.hpp>
#include <pyjs/export_js_module.hpp>
#include <sstream>


namespace py = pybind11;
namespace em = emscripten;

int
run_script(const std::string& workdir, const std::string& script_filename)
{
    py::object scope = py::module_::import("__main__").attr("__dict__");
    std::stringstream code_stream;
    code_stream << "os.chdir('" << workdir << "');";
    try
    {
        py::exec("import os", scope);
        py::exec(code_stream.str().c_str(), scope);

        auto ret = py::eval_file(script_filename, scope);
        return 0;
    }
    catch (py::error_already_set& e)
    {
        std::cout << "error: " << e.what() << "\n";
        return 1;
    }
}


int
run_code(const std::string& code)
{
    py::object scope = py::module_::import("__main__").attr("__dict__");
    try
    {
        py::exec(code, scope);
        return 0;
    }
    catch (py::error_already_set& e)
    {
        std::cout << "error: " << e.what() << "\n";
        return 1;
    }
}

int
n_unfinished()
{
    try
    {
        py::object scope = py::module_::import("__main__").attr("__dict__");
        py::module_ asyncio = py::module_::import("asyncio");
        return asyncio.attr("get_event_loop")().attr("_n_unfinished").cast<int>();
    }
    catch (py::error_already_set& e)
    {
        std::cout << "error: " << e.what() << "\n";
        return 0;
    }
}


em::val
run_async_main(const std::string& workdir, const std::string& script_filename)
{
    // py::object scope = py::module_::import("__main__").attr("__dict__");
    py::object scope = py::dict();
    std::stringstream code_stream;
    code_stream << "os.chdir('" << workdir << "');";

    try
    {
        py::exec("import os", scope);
        py::exec(code_stream.str().c_str(), scope);

        auto ret = py::eval_file(script_filename, scope);

        std::cout << "get the main\n";
        py::object async_main = scope["async_main"];


        py::module_ asyncio = py::module_::import("asyncio");
        py::object main_future = asyncio.attr("ensure_future")(async_main);

        return em::val(std::move(main_future));
    }
    catch (py::error_already_set& e)
    {
        std::cout << "error: " << e.what() << "\n";
        return em::val::undefined();
    }
}

PYBIND11_EMBEDDED_MODULE(pyjs, m)
{
    pyjs::export_pyjs_module(m);
}

EMSCRIPTEN_BINDINGS(my_module)
{
    em::function("run_async_main", &run_async_main);

    em::function("n_unfinished", &n_unfinished);

    pyjs::export_js_module();

    em::function("run_script", &run_script);

    em::function(
        "initialize_interpreter",
        em::select_overload<void()>([]() { py::initialize_interpreter(true, 0, nullptr, false); }));
    em::function("finalize_interpreter",
                 em::select_overload<void()>([]() { py::finalize_interpreter(); }));
}
