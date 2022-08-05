#include <pyjs/export_py_object.hpp>


#include <pybind11/embed.h>
#include <emscripten/bind.h>


namespace pyjs
{
    namespace em = emscripten;


    int n_unfinished()
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


    std::string run_pickled(const std::string& in)
    {
        try
        {
            py::module_ pickle = py::module_::import("marshal");
            py::module_ codecs = py::module_::import("codecs");
            py::module_ types = py::module_::import("types");


            py::object encoded = py::cast(in).attr("encode")();
            py::object decoded = codecs.attr("decode")(encoded, "base64");
            py::object result = pickle.attr("loads")(decoded);

            py::object funcion_code = result["function"];
            py::object function = types.attr("FunctionType")(funcion_code, py::dict());

            py::list args = result["args"];
            py::dict kwargs = result["kwargs"];
            py::object function_result = function(*args, **kwargs);

            py::dict packaged_result;
            packaged_result["result"] = function_result;
            packaged_result["has_err"] = py::cast(false);

            auto raw_dump = pickle.attr("dumps")(packaged_result);
            auto encoded64 = codecs.attr("encode")(raw_dump, "base64");
            auto decoded_ret = encoded64.attr("decode")();
            const std::string as_string = decoded_ret.cast<std::string>();
            return as_string;
        }
        catch (py::error_already_set& e)
        {
            py::module_ pickle = py::module_::import("marshal");
            py::module_ codecs = py::module_::import("codecs");

            py::dict packaged_result;
            packaged_result["has_err"] = py::cast(true);
            packaged_result["err"] = e.what();

            auto raw_dump = pickle.attr("dumps")(packaged_result);
            auto encoded64 = codecs.attr("encode")(raw_dump, "base64");
            auto decoded_ret = encoded64.attr("decode")();
            const std::string as_string = decoded_ret.cast<std::string>();
            return as_string;
        }
    }


    void export_js_module()
    {


        em::class_<py::scoped_interpreter>("Interpreter")
            .constructor<>()
        ;


        export_py_object();

        em::function("cout",
                     em::select_overload<void(const std::string&)>([](const std::string& val)
                                                                   { std::cout << val; }));

        em::function("run_pickled", &run_pickled);


        em::function("n_unfinished", &n_unfinished);


        em::function("initialize_interpreter",
                     em::select_overload<void()>(
                         []() { py::initialize_interpreter(true, 0, nullptr, false); }));
        em::function("finalize_interpreter",
                     em::select_overload<void()>([]() { py::finalize_interpreter(); }));
    }

}
