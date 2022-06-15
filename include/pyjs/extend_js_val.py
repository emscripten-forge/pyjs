
#include "pyjs/macro_magic.hpp"
BEGIN_PYTHON_INIT(pyjs_extend_js_val) R"pycode(#"


import json
import numpy
import sys
import types
import contextlib
from typing import Any
import asyncio


# JsValue *can* hold this as a property
class JsInfo(object):
    def __init__(self, parent=None):
        self._pyjs_parent = parent

_PYJS_JS_INFO_KEY  = '_pyjs_info'
_PYJS_IPYMAGIC_KEY =  "_ipython_canary_method_should_not_exist_"
_PYJS_PROHIBITED_KEYS = set([_PYJS_JS_INFO_KEY, _PYJS_IPYMAGIC_KEY])

def extend_val():

   
    def __val_call(self, *args):
        return apply(self, args=args)

   
    # move all of this impl to a single c++ call
    def val_getattr(self, key):


        ret,err,meta = internal.getattr_try_catch(self, key)
        if err is not None:
            raise error_to_py(err=rr)

        if ret is None:
            # typestring
            if meta == "0":
                return None
            raise AttributeError(f"{self} has no attribute {key}")
        # if meta == "7":
        #     if isinstance(ret, JsValue):
        #         setparent(ret, self)
        return ret


    def val_setattr(self, key, val):
        # if key == _PYJS_JS_INFO_KEY:
        #     super(JsValue, self).__setattr__(key,val)
        # else:
        if (err := internal.setattr_try_catch(self, key, val)) is not None:
            raise error_to_py(err=rr)


    def val_setitem(self, key, val):
        # if key == _PYJS_JS_INFO_KEY:
        #     super(JsValue, self).__setattr__(key,val)
        # else:
        if (err := internal.setattr_try_catch(self, key, val)) is not None:
            raise error_to_py(err=rr)

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

    JsValue.__call__ = __val_call
    JsValue.__getitem__ = val_getattr
    JsValue.__getattr__ = val_getattr
    JsValue.__setattr__ = val_setattr
    JsValue.__setitem__ = val_setitem

    JsValue._asstr_unsafe = lambda self:internal.to_string(self)
    JsValue.__str__ = lambda self : self.toString()
    JsValue.__repr__ = lambda self : self.toString()
    JsValue.__len__ = lambda self : internal.module_property("__len__")(self)
    JsValue.__contains__ = lambda self,q: internal.module_property("__contains__")(self, q)
    JsValue.__eq__ = lambda self,q: internal.module_property("__eq__")(self, q)

    JsValue.new = lambda self,*args : internal.module_property("_new")(self, *args)
    JsValue.to_py = lambda self, converter_options=None: to_py(js_val=self, converter_options=converter_options)
    JsValue.typeof = val_typeof
    JsValue.__iter__ = lambda self : _module._iter(self)
    JsValue.__next__ = val_next

    JsValue.__delattr__ = lambda s,k:_module._delete(s, k)
    JsValue.__delitem__ = lambda s,k: s.delete(k)
    JsValue._to_future = val_to_future
    JsValue.__await__ = lambda s :s._to_future().__await__()


extend_val()
del extend_val



#)pycode"
END_PYTHON_INIT
