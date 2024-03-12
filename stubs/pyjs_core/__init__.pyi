"""This module does blah blah."""

class JsValue:
    """
    A class holding a javascript object/value. 
    """
    def ok_1(self, foo: list[str] = ...) -> None: ...

    def __init__(self, value: Any) -> None:
        """
        Create a new JsValue from a python value. 
        Args:
            value: The value to convert to a JsValue.
            If the value is a primitive type (int, float, str, bool) it will be converted to the corresponding javascript type.
            For any other python object, it will be converted to the javascript class `pyjs.pyobject` which is a wrapper around the python object on the javascript side.
        """
        ...