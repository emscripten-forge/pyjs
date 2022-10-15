#pragma once
#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <emscripten/val.h>
#include <string>

namespace py = pybind11;
namespace em = emscripten;

namespace pyjs
{

    enum class JsType : char
    {
        JS_NULL = '0',
        JS_UNDEFINED = '1',
        JS_OBJECT = '2',
        JS_STR = '3',
        JS_INT = '4',
        JS_FLOAT = '5',
        JS_BOOL = '6',
        JS_FUNCTION = '7'
    };

    std::pair<em::val,bool> implicit_py_to_js(py::object & py_ret);

    bool instanceof (em::val instance, const std::string& cls_name);

    template <class T>
    py::object typed_array_to_numpy_array_impl(em::val js_array)
    {
        em::val js_array_buffer = js_array["buffer"].as<em::val>();

        const unsigned byte_offset = js_array["byteOffset"].as<em::val>().as<unsigned>();
        const unsigned length = js_array["length"].as<unsigned>();
        const unsigned bytes_per_element = js_array["BYTES_PER_ELEMENT"].as<unsigned>();
        const unsigned length_uint8 = length * bytes_per_element;

        // TODO skip for uint8!
        // convert js typed-array into an js-Uint8Array
        em::val js_uint8array = em::val::global("Uint8Array")
                                    .new_(js_array_buffer, byte_offset, length * bytes_per_element);


        py::array_t<T> np_array({ py::ssize_t(length) });

        // copy values from js side to vectors mem
        // - create a javascript "UInt8(!) (not Int8) array"
        //   which is using the vector ptr as buffer
        em::val heap = em::val::module_property("HEAPU8");
        em::val memory = heap["buffer"];
        em::val memory_view = js_uint8array["constructor"].new_(
            memory, reinterpret_cast<uintptr_t>(np_array.data()), length_uint8);

        // - copy the js arrays content into the c++ arrays content
        memory_view.call<void>("set", js_uint8array);

        return np_array;
    }


    py::object typed_array_to_numpy_array(em::val js_array);
    py::object implicit_js_to_py(em::val val);
    py::object implicit_js_to_py(em::val val, const std::string& type_string);


    em::val py_1d_buffer_to_typed_array(py::buffer buffer, bool view);

}
