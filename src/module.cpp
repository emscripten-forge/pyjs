// The builtin Python module `pyjs_core`: the JSProxy type (js_proxy.cpp) and
// the few functions the python package `pyjs` builds everything else from.
// A nanobind module, registered by pyjs_start_python (py_entry.cpp).
#include <nanobind/nanobind.h>

#include "slot.hpp"

#include <emscripten.h>
#include <emscripten/html5.h>

#include <iostream>
#include <string>

namespace nb = nanobind;

// a typed array for wasm memory at `ptr` (`format`: struct format character of
// the items), as view of the memory or as copy; RC_ERROR for unknown formats
EM_JS(int, pyjs_js_typed_array, (double ptr, double nitems, int format, int view, double out), {
    return pj.typedArray(ptr, nitems, format, view, out);
});

// size in bytes (out.num), struct format character (out.aux) of a typed array
// / ArrayBuffer / DataView
EM_JS(int, pyjs_js_buffer_info, (int h, double out), {
    return pj.bufferInfo(h, out);
});

// copy the bytes of a typed array / ArrayBuffer / DataView to `ptr`
EM_JS(void, pyjs_js_buffer_copy, (int h, double ptr), {
    pj.bufferCopy(h, ptr);
});

namespace
{
    // a new reference from the C functions of the core, or their exception
    nb::object checked(PyObject* o)
    {
        if (o == nullptr)
        {
            throw nb::python_error();
        }
        return nb::steal(o);
    }

    // a JS typed array with the items of a contiguous 1d buffer
    nb::object buffer_to_js(nb::handle obj, bool view)
    {
        Py_buffer buffer;
        if (PyObject_GetBuffer(obj.ptr(), &buffer, PyBUF_FORMAT | PyBUF_C_CONTIGUOUS) != 0)
        {
            throw nb::python_error();
        }
        // (no format: unsigned bytes; a byte order / size prefix is skipped)
        const char* format = buffer.format != nullptr ? buffer.format : "B";
        if (*format == '@' || *format == '=' || *format == '<')
        {
            ++format;
        }
        pyjs::Slot out;
        int rc = 1;
        if (buffer.ndim <= 1 && format[0] != 0 && format[1] == 0)
        {
            rc = pyjs_js_typed_array(pyjs::ptr_to_num(buffer.buf),
                                     static_cast<double>(buffer.len / buffer.itemsize),
                                     format[0],
                                     view ? 1 : 0,
                                     pyjs::ptr_to_num(&out));
        }
        const std::string format_copy = format;
        const int ndim = buffer.ndim;
        PyBuffer_Release(&buffer);
        if (rc != 0)
        {
            PyErr_Format(PyExc_TypeError,
                         "a contiguous 1d buffer of numbers is required (ndim %d, format '%s')",
                         ndim,
                         format_copy.c_str());
            throw nb::python_error();
        }
        return checked(pyjs::from_slot(&out));
    }

    // (bytes, struct format character) of a JS typed array / ArrayBuffer / DataView
    nb::object js_to_bytes(nb::handle proxy)
    {
        const int handle = pyjs::js_proxy_handle(proxy.ptr());
        pyjs::Slot out;
        if (handle == 0 || pyjs_js_buffer_info(handle, pyjs::ptr_to_num(&out)) != 0)
        {
            PyErr_SetString(PyExc_TypeError, "a JSProxy of a typed array, ArrayBuffer or DataView is required");
            throw nb::python_error();
        }
        nb::object bytes = checked(PyBytes_FromStringAndSize(nullptr, static_cast<Py_ssize_t>(out.num)));
        pyjs_js_buffer_copy(handle, pyjs::ptr_to_num(PyBytes_AS_STRING(bytes.ptr())));
        const char format[2] = { static_cast<char>(out.aux), 0 };
        return nb::make_tuple(bytes, nb::str(format));
    }

    // replace a hook: keeps the new object alive, forever
    void set_hook(PyObject*& hook, nb::handle value)
    {
        Py_XSETREF(hook, value.is_none() ? nullptr : Py_NewRef(value.ptr()));
    }

    // ----------------------------------------------------------------------
    // emscripten main loop / requestAnimationFrame loop
    // ----------------------------------------------------------------------
    // one iteration of the main loop: call the Python callable
    void main_loop_callback(void* callable)
    {
        PyObject* ret = PyObject_CallNoArgs(static_cast<PyObject*>(callable));
        if (ret == nullptr)
        {
            std::cerr << "Error calling Python callback:" << std::endl;
            PyErr_Print();
        }
        Py_XDECREF(ret);
    }

    // emscripten_cancel_main_loop alone fails strangely: a new (empty) loop
    // must be set right away
    void noop_callback()
    {
    }

    // one requestAnimationFrame tick: calls the Python callable with the frame
    // time (ms); the loop continues while it returns something truthy. The
    // loop owns a reference to the callable, released when the loop ends.
    bool animation_frame_callback(double time, void* user_data)
    {
        PyObject* callable = static_cast<PyObject*>(user_data);
        PyObject* time_obj = PyFloat_FromDouble(time);
        PyObject* ret = time_obj != nullptr ? PyObject_CallOneArg(callable, time_obj) : nullptr;
        Py_XDECREF(time_obj);

        bool keep_running = false;
        if (ret == nullptr)
        {
            std::cerr << "Error in animation frame callback, stopping the loop:" << std::endl;
            PyErr_Print();
        }
        else
        {
            const int truth = PyObject_IsTrue(ret);
            Py_DECREF(ret);
            if (truth < 0)
            {
                PyErr_Print();
            }
            keep_running = truth > 0;
        }
        if (!keep_running)
        {
            Py_DECREF(callable);
        }
        return keep_running;
    }
}

NB_MODULE(pyjs_core, m)
{
    // the interpreter is never finalized
    nb::set_leak_warnings(false);

    if (!pyjs::js_proxy_init(m.ptr()))
    {
        throw nb::python_error();
    }

    m.def("global_this", []() { return checked(pyjs::js_global(0)); }, "JSProxy of globalThis");
    m.def("module", []() { return checked(pyjs::js_global(1)); }, "JSProxy of the emscripten Module");
    m.def(
        "create_proxy",
        [](nb::handle obj, bool always) { return checked(pyjs::create_proxy(obj.ptr(), always)); },
        nb::arg("obj"),
        nb::arg("always") = true,
        "A JSProxy of a PyProxy of obj, which lives until its destroy() is called. Objects that are "
        "converted to JavaScript values (None, bool, int, float, str, JSProxy) have no proxy: with "
        "always=True that is a TypeError, with always=False obj itself is returned.");
    m.def(
        "run_sync",
        [](nb::handle promise) { return checked(pyjs::run_sync(promise.ptr())); },
        "block until the promise settles (JSPI, only where suspending is possible)");
    m.def(
        "to_py",
        [](nb::handle obj, int depth) { return checked(pyjs::deep_to_py(obj.ptr(), depth)); },
        // (.none(): nanobind refuses None as argument unless it is allowed
        // explicitly; None is a legitimate value here, JavaScript's undefined)
        nb::arg("obj").none(),
        nb::arg("depth") = -1,
        "A deep copy of a JavaScript value as Python objects: Array -> list, Map / plain Object -> dict, "
        "Set -> set, typed array / ArrayBuffer -> memoryview. depth: levels of containers to convert, "
        "-1 for all. Anything that is no JSProxy is returned as it is.");
    m.def(
        "to_js",
        [](nb::handle obj, int depth) { return checked(pyjs::deep_to_js(obj.ptr(), depth)); },
        nb::arg("obj").none(),
        nb::arg("depth") = -1,
        "A deep copy of a Python value as JavaScript value: list / tuple / sequence -> Array, dict -> "
        "Object, set -> Set, buffer -> typed array; other objects become proxies. depth: levels of "
        "containers to convert, -1 for all.");
    m.def("buffer_to_js", &buffer_to_js, "a typed array for a 1d buffer (view: of the wasm memory, no copy)");
    m.def("js_to_bytes", &js_to_bytes, "(bytes, format) of a typed array / ArrayBuffer / DataView");

    // the Python side of the core (None: unset)
    m.def(
        "set_hooks",
        [](nb::handle raise_js_error, nb::handle format_exception, nb::handle await_js, nb::handle jsnull,
           nb::handle bigint_type, nb::handle sequence_abc, nb::handle to_py_with_converter)
        {
            pyjs::Hooks& hooks = pyjs::hooks();
            set_hook(hooks.raise_js_error, raise_js_error);
            set_hook(hooks.format_exception, format_exception);
            set_hook(hooks.await_js, await_js);
            set_hook(hooks.jsnull, jsnull);
            set_hook(hooks.bigint_type, bigint_type);
            set_hook(hooks.sequence_abc, sequence_abc);
            set_hook(hooks.to_py_with_converter, to_py_with_converter);
        });

    m.def("_set_main_loop_callback",
          [](nb::handle callback, int fps)
          { emscripten_set_main_loop_arg(main_loop_callback, callback.ptr(), fps, false); });
    m.def("_cancel_main_loop", []() { emscripten_cancel_main_loop(); });
    m.def("_set_noop_main_loop", []() { emscripten_set_main_loop(noop_callback, 1, false); });
    m.def("_request_animation_frame_loop",
          [](nb::handle callback)
          {
              // released by animation_frame_callback
              Py_INCREF(callback.ptr());
              emscripten_request_animation_frame_loop(animation_frame_callback, callback.ptr());
          });
}
