import asyncio


# JsValue *can* hold this as a property
class JsInfo(object):
    def __init__(self, parent=None):
        self._pyjs_parent = parent


# _PYJS_JS_INFO_KEY  = '_pyjs_info'
# _PYJS_IPYMAGIC_KEY =  "_ipython_canary_method_should_not_exist_"
# _PYJS_PROHIBITED_KEYS = set([_PYJS_JS_INFO_KEY, _PYJS_IPYMAGIC_KEY])


def _to_string(val):
    if _module._is_undefined(val):
        return "undefined"
    elif _module._is_null(val):
        return "null"
    else:
        return val.toString()


def extend_val():
    def __val_call(self, *args):
        return apply(self, args=args)

    def val_next(self):
        res = self.next()
        if res.done:
            raise StopIteration
        else:
            return res.value

    @property
    def val_typeof(s):
        return _module._typeof(s)

    def val_to_future(self, callback=None):
        future = asyncio.Future()

        def _then(val, cb):
            if cb is not None:
                val = cb(val)
            future.set_result(val)

        def _catch(str_err):
            str_err = to_py(str_err)
            future.set_exception(RuntimeError(str_err))

        binded_then = functools.partial(_then, cb=callback)
        _module._set_promise_then_catch(self, JsValue(binded_then), JsValue(_catch))
        return future

    JsValue.__call__ = __val_call

    JsValue._asstr_unsafe = lambda self: internal.to_string(self)
    JsValue.__str__ = lambda self: _to_string(self)
    JsValue.__repr__ = lambda self: _to_string(self)
    JsValue.__len__ = lambda self: internal.module_property("__len__")(self)
    JsValue.__contains__ = lambda self, q: internal.module_property("__contains__")(
        self, q
    )
    JsValue.__eq__ = lambda self, q: internal.module_property("__eq__")(self, q)

    JsValue.new = lambda self, *args: internal.module_property("_new")(self, *args)
    JsValue.to_py = lambda self, converter_options=None: to_py(
        js_val=self, converter_options=converter_options
    )
    JsValue.typeof = val_typeof
    JsValue.__iter__ = lambda self: _module._iter(self)
    JsValue.__next__ = val_next

    JsValue.__delattr__ = lambda s, k: _module._delete(s, k)
    JsValue.__delitem__ = lambda s, k: s.delete(k)
    JsValue._to_future = val_to_future
    JsValue.__await__ = lambda s: s._to_future().__await__()
    JsValue.jcall = lambda s, *args: japply(s, args)


extend_val()
del extend_val
