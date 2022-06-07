#include "pyjs/macro_magic.hpp"
BEGIN_PYTHON_INIT(pyjs_core) R"pycode(#"


import json
import numpy
import sys
import types
import contextlib
from typing import Any


def install_submodules():

    def _js_mod__getattr__(name: str) -> Any:
        ret = internal.global_property(name)
        if internal.is_undefined_or_null(ret):
            raise AttributeError(f"has no attribute {name}")
        return _build_in_to_python(ret)  

    js = sys.modules["pyjs.js"] = types.ModuleType("js")
    js.__getattr__ = _js_mod__getattr__

    def _module_mod__getattr__(name: str) -> Any:
        ret = internal.module_property(name)
        if internal.is_undefined_or_null(ret):
            raise AttributeError(f"has no attribute {name}")
        return _build_in_to_python(ret)  
        
    _module = sys.modules["pyjs._module"] = types.ModuleType("_module")
    _module.__getattr__ = _module_mod__getattr__


install_submodules()
del install_submodules

js = sys.modules["pyjs.js"]
_module = sys.modules["pyjs._module"]




# def new(cls, *args):
#     return internal.val_new(cls, *args)

def new(cls, *args):
    return internal.module_property("_new")(*args)

def type_str(x):
    return internal.type_str(x)


def create_callable(py_function):
    _js_py_object = js_py_object(py_function)
    return _js_py_object['__call__'].bind(_js_py_object),  _js_py_object

@contextlib.contextmanager
def callable_context(py_function):
    cb, handle = create_callable(py_function)
    yield cb
    handle.delete()



def create_once_callable(py_function):
    js_py_function = js_py_object(py_function)
    once_callable = _module._create_once_callable(js_py_function)
    return once_callable

def ensure_js_val(arg):
    if isinstance(arg, JsValue):
        return arg
    else:
        return JsValue(arg)


def _error_checked(ret):

    is_error = internal.is_error(ret)
    if is_error:
        err = internal.get_error(ret)
        # internal.console_log("ERROR",err)
        error_str = js.JSON.stringify(err, js.Object.getOwnPropertyNames(err))
        raise RuntimeError(error_str)

    return ret


def apply(js_function, args):
    #print("apply",js_function,args)
    js_array_args = js_array()
    for arg in args:
        js_arg = ensure_js_val(arg)
        internal.val_call(js_array_args, "push", js_arg)

    #print("apply try catch!")
    applyTryCatch = internal.module_property('_apply_try_catch')
    ret  = internal.val_function_call(applyTryCatch, js_function, js_null(), js_array_args)
    return _build_in_to_python(_error_checked(ret))



#)pycode"
END_PYTHON_INIT
