#include <iostream>
#include <filesystem>

#include <pyjs/export_py_object.hpp>
#include <pyjs/convert.hpp>
#include <pyjs/untar.hpp>
#include <pyjs/install_conda_file.hpp>

#include <pybind11/embed.h>
#include <emscripten/bind.h>
#include <pybind11/pybind11.h>


namespace pyjs
{
    namespace em = emscripten;
    namespace py = pybind11;


    em::val eval(const  std::string & code, py::object & globals, py::object & locals)
     {       em::val ret = em::val::object();
        try
        {
            py::object py_ret = py::eval(code, globals, locals);
            ret.set("has_err",em::val(false));
            auto [jsval, is_proxy] = implicit_py_to_js(py_ret);
            ret.set("ret",jsval);
            ret.set("is_proxy",is_proxy);
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



    em::val exec(const  std::string & code, py::object & globals, py::object & locals)
    {
        em::val ret = em::val::object();
        try
        {
            py::exec(code, globals, locals);
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


    em::val eval_file(const  std::string & filename, py::object & globals, py::object & locals)
    {
        em::val ret = em::val::object();
        try
        {
            py::eval_file(filename, globals, locals);
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

    void set_env(const std::string & key, const std::string & value)
    {
        setenv(key.c_str(), value.c_str(), 1);
    }

    void create_directories(const std::string & p)
    {
        std::filesystem::create_directories(std::filesystem::path(p));
    }
    bool is_directory(const std::string & p)
    {
        return std::filesystem::is_directory(std::filesystem::path(p));
    }

    void export_js_module()
    {
        // interpreter itself,
        em::class_<py::scoped_interpreter>("_Interpreter")
            .constructor<>()
        ;

        em::function("_eval", &eval);
        em::function("_exec", &exec);
        em::function("_eval_file", &eval_file);

        em::function("create_directories", &create_directories);
        em::function("is_directory", &is_directory);


        em::function("_untar", &untar);
        em::function("_install_conda_file", &install_conda_file);
        em::function("setenv", &set_env);

        // py-object (proxy)
        export_py_object();

        // main scope
        em::function("main_scope",em::select_overload<py::object()>(
            []()->py::object{
                auto scope = py::module_::import("__main__").attr("__dict__");
                //py::exec("import pyjs;import asyncio", scope);
                return scope;
            }
        ));

        em::function("cout",
                     em::select_overload<void(const std::string&)>([](const std::string& val)
                                                                   { std::cout << val; }));


    }

}
