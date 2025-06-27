#include <pybind11/pybind11.h>

#include <emscripten.h>
#include <emscripten/val.h>
#include <emscripten/bind.h>

#include <iostream>
#include <filesystem>

#include <pyjs/export_js_proxy.hpp>
#include <pyjs/export_pyjs_module.hpp>

// python

namespace py = pybind11;
namespace em = emscripten;

namespace pyjs
{   

    // struct LoopContext
    // {
    //     py::object m_callback;
    //     bool m_cancel_loop_on_error = true; // default to true
    //     bool m_exit_loop = false;

    //     LoopContext(py::object callback, bool cancel_loop_on_error)
    //         : m_callback(std::move(callback)), m_cancel_loop_on_error(cancel_loop_on_error), m_exit_loop(false) {}
    // };


    void wrapped_callback(void* cb_ptr) {
        // Reinterpret the void pointer back to a PyObject pointer
        auto py_object = reinterpret_cast<PyObject*>(cb_ptr);
        if(!py_object) {
            std::cerr << "Error: callback pointer is null." << std::endl;
        }
        // We can use PyObject_CallObject to call the Python function
        if (PyObject_CallNoArgs(py_object) == nullptr) {
            // If the call fails, we can print the error
            std::cerr << "Error calling Python callback:" << std::endl;
            PyErr_Print();
        }
    };

    void noop_callback() {
        // This is a no-op callback, it does nothing
        
        // we see a strange error when we run emscripten_cancel_main_loop
        // **WITHOUT setting a new loop right away**
        // so instead of just cancelling the loop, we need
        // to cancel and right away set a new loop
    }

    void self_cancel_callback() {
       emscripten_cancel_main_loop();
    };


    void export_main_loop_callbacks(py::module_& pyjs_module)
    {


        
        // // class for loop context
        // py::class_<LoopContext>(pyjs_module, "LoopContext")
        //     .def(py::init<py::object, bool>(), py::arg("callback"), py::arg("cancel_loop_on_error") = true)
        //     .def_readwrite("exit_loop", &LoopContext::m_exit_loop)
        // ;
        


        // Export main loop callbacks
        pyjs_module.def("_set_main_loop_callback", [](py::handle  callback, int fps) {
            
            // get a PyObject * from the handle
            auto py_object = callback.ptr();

            // convert the PyObject to void*
            void* callback_ptr = reinterpret_cast<void*>(py_object);


            // use emscripten_set_main_loop_arg
            emscripten_set_main_loop_arg(
                wrapped_callback,
                callback_ptr, // pass the callback pointer as argument
                fps, // frames per second
                false 
            );
        });

        // explicit cancel main loop
        pyjs_module.def("_cancel_main_loop", []() {
            // This will cancel the main loop if it is currently running
            emscripten_cancel_main_loop();
        });

        pyjs_module.def("_set_noop_main_loop", []() {
            // This will set a no-op main loop
            emscripten_set_main_loop(noop_callback, 1, false); // set a no-op loop to avoid errors
        });
                        
    }



    void export_pyjs_module(py::module_& pyjs_module)
    {
        export_js_proxy(pyjs_module);
        export_main_loop_callbacks(pyjs_module);
        
    }
}
