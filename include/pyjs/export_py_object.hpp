#include <emscripten/val.h>
#include <emscripten/bind.h>
#include <pyjs/convert.hpp>
#include <strings.h>

namespace py = pybind11;
namespace em = emscripten;

namespace pyjs
{


void export_py_object()
{
    em::class_<py::object>("pyobject")


        // // variadic-call
        // .function("__call_variadic__", 
        //     em::select_overload<int(py::object &)>(
        //         [](py::object & pyobject)
        //         {
        //             // pyobject is ALWAYS holding an emscripten::val
        //             // holding an array of arguments

        //             //pyobject();
        //             return 1;
        //         }
        //     )
        // )

        // 0-ary
        .function("__call__", 
            em::select_overload<em::val(py::object &)>(
                [](py::object & pyobject) ->em::val
                {
                    try{
                        py::gil_scoped_acquire acquire;
                        py::object ret = pyobject();
                        return em::val(std::move(ret));
                    }
                    catch(py::error_already_set& e){
                        std::cout<<"error: "<<e.what()<<"\n";
                        return em::val::null();
                    }
                }
            )
        )


        // 1-ary
        .function("__call__", 
            em::select_overload<em::val(py::object &, em::val  val)>(
                [](py::object & pyobject, em::val arg1) ->em::val
                {
                    try{
                        py::gil_scoped_acquire acquire;
                        py::object ret = pyobject(arg1);
                        return em::val(std::move(ret));
                    }
                    catch(py::error_already_set& e){
                        std::cout<<"error: "<<e.what()<<"\n";
                        return em::val::null();
                    }
                }
            )
        )

        .function("__usafe_void_void__", 
            em::select_overload<void(py::object &)>(
                [](py::object & pyobject) 
                {
                    {
                        py::gil_scoped_acquire acquire;
                        pyobject();
                    }
                }
            )
        )

        .function("__usafe_void_val__", 
            em::select_overload<void(py::object &, em::val)>(
                [](py::object & pyobject, em::val val) 
                {
                    {
                        py::gil_scoped_acquire acquire;
                        pyobject(val);
                    }
                }
            )
        )

        // // 1-ary
        // .function("__call__", 
        //     em::select_overload<int(py::object &, em::val)>([](py::object & pyobject, em::val arg1){
        //         // py::object = convert_impl(arg1);
        //         pyobject(arg1);
        //         return 1;
        //     })
        // )

        // // 2-ary
        // .function("__call__", 
        //     em::select_overload<int(py::object &, em::val, em::val)>([](py::object & pyobject, em::val arg1, em::val arg2)
        //     {
        //         // py::object = convert_impl(arg1);
        //         pyobject(arg1, arg2);
        //         return 1;
        //     })
        // )
        // // 3-ary
        // .function("__call__", 
        //     em::select_overload<int(py::object &, em::val, em::val, em::val)>([](py::object & pyobject, em::val arg1, em::val arg2, em::val arg3)
        //     {
        //         // py::object = convert_impl(arg1);
        //         pyobject(arg1, arg2, arg3);
        //         return 1;
        //     })
        // )
        // // 4-ary
        // .function("__call__", 
        //     em::select_overload<int(py::object &, em::val, em::val, em::val, em::val)>([](py::object & pyobject, em::val arg1, em::val arg2, em::val arg3, em::val arg4)
        //     {
        //         // py::object = convert_impl(arg1);
        //         pyobject(arg1, arg2, arg3, arg4);
        //         return 1;
        //     })
        // )
    ;

}

}