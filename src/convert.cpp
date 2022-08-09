#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <emscripten/val.h>
#include <string>
#include <pyjs/convert.hpp>

namespace py = pybind11;
namespace em = emscripten;

namespace pyjs
{
    em::val implicit_conversion(py::object& py_ret)
    {
        py::module_ pyjs = py::module_::import("pyjs");
        const std::string info = pyjs.attr("implicit_convert_info")(py_ret).cast<std::string>();
        if (info == "int")
        {
            return em::val(py_ret.cast<int>());
        }
        else if (info == "str")
        {
            return em::val(py_ret.cast<std::string>());
        }
        else if (info == "bool")
        {
            return em::val(py_ret.cast<bool>());
        }
        else if (info == "double")
        {
            return em::val(py_ret.cast<double>());
        }
        else if (info == "None")
        {
            return em::val::undefined();
        }
        else
        {
            // return em::val(py_ret);
            return em::val::module_property("make_proxy")(em::val(py_ret));
        }
    }


    bool instanceof (em::val instance, const std::string& cls_name)
    {
        return em::val::module_property("_instanceof")(instance, em::val::global(cls_name.c_str()))
            .as<bool>();
    };


    py::object typed_array_to_numpy_array(em::val js_array)
    {
        if (instanceof (js_array, "Int8Array"))
        {
            return typed_array_to_numpy_array_impl<int8_t>(js_array);
        }
        else if (instanceof (js_array, "Uint8Array"))
        {
            return typed_array_to_numpy_array_impl<uint8_t>(js_array);
        }
        else if (instanceof (js_array, "Uint8ClampedArray"))
        {
            return typed_array_to_numpy_array_impl<uint8_t>(js_array);
        }
        else if (instanceof (js_array, "Int16Array"))
        {
            return typed_array_to_numpy_array_impl<int16_t>(js_array);
        }
        else if (instanceof (js_array, "Uint16Array"))
        {
            return typed_array_to_numpy_array_impl<uint16_t>(js_array);
        }
        else if (instanceof (js_array, "Int32Array"))
        {
            return typed_array_to_numpy_array_impl<int32_t>(js_array);
        }
        else if (instanceof (js_array, "Uint32Array"))
        {
            return typed_array_to_numpy_array_impl<uint32_t>(js_array);
        }
        else if (instanceof (js_array, "Float32Array"))
        {
            return typed_array_to_numpy_array_impl<float>(js_array);
        }
        else if (instanceof (js_array, "Float64Array"))
        {
            return typed_array_to_numpy_array_impl<double>(js_array);
        }
        else if (instanceof (js_array, "BigInt64Array"))
        {
            return typed_array_to_numpy_array_impl<int64_t>(js_array);
        }
        else if (instanceof (js_array, "BigUint64Array"))
        {
            return typed_array_to_numpy_array_impl<uint64_t>(js_array);
        }
        else
        {
            throw pybind11::type_error("unknown array type");
        }
    }

    py::object implicit_to_py(em::val val, const std::string& type_string)
    {
        if (type_string.size() == 1)
        {
            const char s = type_string[0];
            switch (s)
            {
                case static_cast<char>(JsType::JS_NULL):
                {
                    return py::none();
                }
                case static_cast<char>(JsType::JS_UNDEFINED):
                {
                    return py::none();
                }
                // 2 is object
                case static_cast<char>(JsType::JS_STR):
                {
                    return py::cast(val.as<std::string>());
                }
                case static_cast<char>(JsType::JS_INT):
                {
                    const auto double_number = val.as<double>();
                    const auto rounded_double_number = std::round(double_number);
                    return py::cast(int(rounded_double_number));
                }
                case static_cast<char>(JsType::JS_FLOAT):
                {
                    return py::cast(val.as<double>());
                }
                case static_cast<char>(JsType::JS_BOOL):
                {
                    return py::cast(val.as<bool>());
                }
                default:
                {
                    return py::cast(val);
                }
            }
        }
        else
        {
            return py::cast(val);
        }
    }

}
