"""JavaScript errors as Python exceptions.

When JavaScript code called from Python throws, the call raises a
`JSException`. There is one class for all of them, like in pyodide and
PEP 818; the kind of error is in its `name`:

```python
try:
    js.JSON.parse("{not json")
except JSException as e:
    assert e.name == "SyntaxError"
    print(e.message)
```

JavaScript can throw any value, not only `Error` objects (``throw "text"``,
``throw 42``). Those raise a `JSException` too; the thrown value is always
available as `js_error`.
"""

from pyjs_core import JSProxy, global_this

__all__ = ["JSException"]

_js = global_this()

# Gives back its argument. Used by error_to_py: a JS function call is the
# one place where the core turns a JS value into the right Python value (see
# there).
_identity = _js.Function("x", "return x;")


def _text_attribute(err, name):
    """the attribute `name` of a thrown value if it is a non-empty string,
    else None (anything can be thrown: a string has no `message`, an object
    may have a `name` that is no string, ...)"""
    try:
        value = getattr(err, name)
    except Exception:
        return None
    return value if isinstance(value, str) and value else None


def _message(err):
    """The text of a thrown value: the `message` of an Error; for other
    thrown values (strings, numbers, plain objects) the value itself as text,
    since that is all the information there is."""
    message = _text_attribute(err, "message")
    if message is not None:
        return message
    if isinstance(err, JSProxy):
        try:
            # (a plain object: its properties as JSON)
            return str(_js.JSON.stringify(err, _js.Object.getOwnPropertyNames(err)))
        except Exception:
            return str(err)
    return str(err)


# also a RuntimeError: awaiting a rejected promise used to raise RuntimeError,
# `except RuntimeError` keeps working
class JSException(RuntimeError):
    """A value thrown by JavaScript (usually an ``Error``), raised in Python.

    Attributes:
        name: the kind of error, the `name` property of the JavaScript error:
            ``"TypeError"``, ``"RangeError"``, ``"AbortError"``, ... and
            ``"Error"`` for thrown values that have no name.
        message: the `message` property of the JavaScript error; for thrown
            values that are no errors, the value as text.
        stack: the JavaScript stack trace, if the error has one, else None.
        js_error: the thrown value itself: a `JSProxy` of the error object,
            or the Python value for a thrown string / number / ...
    """

    def __init__(self, js_error, message=None):
        self.js_error = js_error
        self.name = _text_attribute(js_error, "name") or "Error"
        self.message = _message(js_error) if message is None else message
        self.stack = _text_attribute(js_error, "stack")
        # str(e) is "Name: message", like JavaScript shows errors (and
        # pyodide): "TypeError: x is not a function"
        super().__init__(f"{self.name}: {self.message}")

    # A JavaScript Error object that reaches python (as value, not thrown)
    # IS a JSException (PEP 818): it can be raised. Passed back to
    # JavaScript it is the Error object again (the core takes `js_error`).
    # Its other properties are reachable as attributes, like those of a
    # JSProxy:
    def __getattr__(self, name):
        # (only called for names that are not found the normal way;
        # `js_error` itself is always found, except while unpickling)
        if name == "js_error":
            raise AttributeError(name)
        return getattr(self.js_error, name)

    def __reduce__(self):
        # Pickled without the JavaScript object (that cannot leave the
        # page): name, message and stack only.
        return (_unpickle_jsexception, (self.name, self.message, self.stack))


def _unpickle_jsexception(name, message, stack):
    """a JSException from its pickled parts (js_error: None)"""
    exception = JSException(None, message)
    exception.name = name
    exception.stack = stack
    return exception


def error_to_py(err):
    """The exception (not raised) for a value thrown by JavaScript.

    How a thrown value gets here (Python called into JavaScript, which
    threw):

    1. the JS side of the operation catches the value, keeps it in the
       handle table and returns RC_ERROR; the result slot (tag T_ERROR)
       holds the handle (src/js/jsops.ts, `writeJsError` in codec.ts)
    2. C++ `raise_from_slot` (src/js_proxy.cpp) wraps the handle in a
       *plain* JSProxy, whatever was thrown, and calls the hook
       `raise_js_error` = `error_to_py_and_raise` (below), which calls this
    3. here `err` is therefore always a JSProxy, also for `throw "text"` or
       `throw 42`. Passing it through the JS function `_identity` sends the
       value to JavaScript and back; on the way back the core converts it
       the normal way (`from_slot` in src/js_proxy.cpp):
         - an Error object (flag JS_ERROR) -> the hook `jsexception_type`
           makes a JSException of it (PEP 818: a JS Error in Python IS a
           JSException)
         - a primitive (string, number, ...) -> the Python value
         - any other object -> a JSProxy again
    4. what is no JSException yet (primitive, other object) is wrapped in
       one; error_to_py_and_raise raises it.
    """
    if isinstance(err, JSProxy):
        err = _identity(err)
    if isinstance(err, JSException):
        return err
    return JSException(err)


def error_to_py_and_raise(err):
    """Raise the exception for a value thrown by JavaScript. The core calls
    this whenever a JavaScript operation started from Python threw."""
    raise error_to_py(err)
