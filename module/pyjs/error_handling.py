from pyjs_core import js

# and object holding a javascript
class JsHolder(object):
    def __init__(self, js_proxy):
        self._js_proxy = js_proxy

    def get_js_proxy(self):
        return self._js_proxy


def _js_error_message(err):
    """the `message` of a JavaScript error (like pyodide), for other thrown
    values (strings, plain objects, ...) the value as JSON"""
    try:
        message = err.message
    except Exception:
        message = None
    if isinstance(message, str) and message:
        return message
    return js.JSON.stringify(err, js.Object.getOwnPropertyNames(err))


# also a RuntimeError: awaiting a rejected promise used to raise RuntimeError,
# `except RuntimeError` keeps working
class JsException(JsHolder, RuntimeError):
    def __init__(self, err, message=None):

        if message is None:
            message = _js_error_message(err)

        self.name = "UnknownError"
        try:
            self.name = err.name
        except  AttributeError:
            pass

        self.message = message

        # i
        Exception.__init__(self, self.message)
        JsHolder.__init__(self, js_proxy=err)


class JsGenericError(JsException):
    def __init__(self, err):
        super().__init__(err=err)
        self.value = err


class JsError(JsException):
    def __init__(self, err):
        super().__init__(err=err)


class JsInternalError(JsError):
    def __init__(self, err):
        super().__init__(err=err)


class JsRangeError(JsError):
    def __init__(self, err):
        super().__init__(err=err)


class JsReferenceError(JsError):
    def __init__(self, err):
        super().__init__(err=err)


class JsSyntaxError(JsError):
    def __init__(self, err):
        super().__init__(err=err)


class JsTypeError(JsError):
    def __init__(self, err):
        super().__init__(err=err)


class JsURIError(JsError):
    def __init__(self, err):
        super().__init__(err=err)
