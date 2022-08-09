#include <iostream>

#include <pyjs/export_py_object.hpp>
#include <pyjs/convert.hpp>
#include <pybind11/embed.h>
#include <emscripten/bind.h>

#include <pybind11/pybind11.h>


namespace pyjs
{
    namespace em = emscripten;
    namespace py = pybind11;


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


    em::val eval(py::scoped_interpreter  & ,const  std::string & code, const py::object & scope)
    {
        em::val ret = em::val::object();
        try
        {
            py::object py_ret = py::eval(code, scope);
            ret.set("has_err",em::val(false));
            ret.set("ret",implicit_conversion(py_ret));
            return ret;
        }
        catch (py::error_already_set& e)
        {
           ret.set("has_err",em::val(true));
           ret.set("message",em::val(std::string(e.what())));
           ret.set("error",em::val(std::string(e.what())));
           return ret;
        }
    }


    em::val exec(py::scoped_interpreter  & ,const  std::string & code, const py::object & scope)
    {
        em::val ret = em::val::object();
        try
        {
            py::exec(code, scope);
            ret.set("has_err",em::val(false));
            return ret;
        }
        catch (py::error_already_set& e)
        {
           ret.set("has_err",em::val(true));
           ret.set("message",em::val(std::string(e.what())));
           ret.set("error",em::val(std::string(e.what())));
           return ret;
        }
    }

    em::val eval_file(py::scoped_interpreter  & ,const  std::string & filename, const py::object & scope)
    {
        em::val ret = em::val::object();
        try
        {
            py::eval_file(filename, scope);
            ret.set("has_err",em::val(false));
            return ret;
        }
        catch (py::error_already_set& e)
        {
           ret.set("has_err",em::val(true));
           ret.set("message",em::val(std::string(e.what())));
           ret.set("error",em::val(std::string(e.what())));
           return ret;
        }
    }




    void export_js_module()
    {


        // interpreter itself, note that only one interpreter at the time allowed
        em::class_<py::scoped_interpreter>("Interpreter")
            .constructor<>()
            .function("_eval", &eval)
            .function("_exec", &exec)
            .function("_eval_file", &eval_file)
        ;

        // py-object (proxy)
        export_py_object();

        // main scope
        em::function("main_scope",em::select_overload<py::object()>(
            []()->py::object{ return py::module_::import("__main__").attr("__dict__"); }
        ));

        // eval_expr,
        // eval_single_statement,
        // eval_statements


        // // run-code
        // em::function("eval_expr",
        //     em::select_overload<py::object()>(
        //     []()->py::object{

        //     }
        // ));

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
