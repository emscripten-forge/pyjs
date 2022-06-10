#include "pyjs/macro_magic.hpp"
BEGIN_PYTHON_INIT(pyjs_extend_js_val) R"pycode(#"


import json
import numpy
import sys
import types
import contextlib
from typing import Any
import asyncio

def extend_val():

    def __val_call(self, *args):

        if hasattr(self, '_pyjs_parent'):
            bound = internal.val_bind(self, self._pyjs_parent)
            return apply(bound, args=args)
            #return member_apply(self._pyjs_parent,js_function=self, args=args)
        else:
            return apply(self, args=args)
   

    def val_getattr(self, key):
        if key == "_ipython_canary_method_should_not_exist_":
            return AttributeError()

        ts = type_str(self)
        if internal.is_undefined_or_null(self):
            raise AttributeError()

        if(key == "_pyjs_parent"):
            raise AttributeError()

        ret = _error_checked(internal.getattr_try_catch(self, key))

        if internal.is_undefined_or_null(ret):
            raise AttributeError(f"{self} has no attribute {key}")
        ret._pyjs_parent = self
        return _build_in_to_python(ret)


    def val_setattr(self, key, val):
        if key == "_pyjs_parent":
            return super(JsValue, self).__setattr__(key,val)
        else:
            _error_checked(internal.setattr_try_catch(self, key, val))

    def val_setitem(self, key, val):
        if key == "_pyjs_parent":
            return super(JsValue, self).__setattr__(key,val)
        else:
            _error_checked(internal.setattr_try_catch(self, key, val))

    def val_next(self):
        res = self.next()
        if res.done:
            raise StopIteration
        else:
            return res.value

    @property
    def val_typeof(s):
        return _module._typeof(s)


    def val_to_future(self):
        future = asyncio.Future()

        def _then(val):
            future.set_result(val)

        def _catch(str_err):
            str_err = to_py(str_err)
            future.set_exception(RuntimeError(str_err))

        _module._set_promise_then_catch(self, JsValue(_then), JsValue(_catch))
        return future


    def val__await__(self):
        future = asyncio.Future()

        def _then(val):
            future.set_result(val)

        def _catch(str_err):
            str_err = to_py(str_err)
            future.set_exception(RuntimeError(str_err))

        _module._set_promise_then_catch(self, JsValue(_then), JsValue(_catch))
        return self._to_future().__await__()

    JsValue.__call__ = __val_call
    JsValue.__getitem__ = val_getattr
    JsValue.__getattr__ = val_getattr
    JsValue.__setattr__ = val_setattr
    JsValue.__setitem__ = val_setitem

    JsValue.__str__ = lambda self : self.toString()
    JsValue.__repr__ = lambda self : self.toString()
    JsValue.__len__ = lambda self : internal.module_property("__len__")(self)
    JsValue.__contains__ = lambda self,q: internal.module_property("__contains__")(self, q)
    JsValue.__eq__ = lambda self,q: internal.module_property("__eq__")(self, q)

    JsValue.new = lambda self,*args : internal.module_property("_new")(self, *args)
    JsValue.to_py = lambda self, max_depth=None: to_py(js_val=self, max_depth=max_depth)
    JsValue.typeof = val_typeof
    JsValue.__iter__ = lambda self : _module._iter(self)
    JsValue.__next__ = val_next

    JsValue.__delattr__ = lambda s,k:_module._delete(s, k)
    JsValue.__delitem__ = lambda s,k: s.delete(k)
    JsValue._to_future = val_to_future
    JsValue.__await__ = val__await__


extend_val()
del extend_val



#)pycode"
END_PYTHON_INIT
