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

# gives back its argument. Used to turn a JSProxy of a thrown *primitive*
# (JavaScript can throw anything: `throw "text"`, `throw 42`) into the Python
# value: passing the proxy to JavaScript hands over the primitive, and a
# primitive coming back is converted instead of proxied.
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
        super().__init__(self.message)


def error_to_py(err):
    """The exception (not raised) for a value thrown by JavaScript."""
    if isinstance(err, JSProxy):
        # a proxy of a primitive (see _identity) becomes the Python value
        err = _identity(err)
    return JSException(err)


def error_to_py_and_raise(err):
    """Raise the exception for a value thrown by JavaScript. The core calls
    this whenever a JavaScript operation started from Python threw."""
    raise error_to_py(err)
