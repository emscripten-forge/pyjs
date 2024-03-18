"""This module does blah blah."""

from typing import Any


class JsValue:
    """
    A class holding a javascript object/value. 
    """


    def __init__(self, value: Any) -> None:
        """
        Create a new JsValue from a python value. 
        Args:
            value: The value to convert to a JsValue.
            If the value is a primitive type (int, float, str, bool) it will be converted to the corresponding javascript type.
            For any other python object, it will be converted to the javascript class `pyjs.pyobject` which is a wrapper around the python object on the javascript side.
        """
        ...
    
    # def __getitem__(self, key: Union[str, int]) -> Any:
    
    def __call__(self, *args: Any) -> Any: 
        """
        Call the javascript object as a function.

        Args:
            *args: The arguments to pass to the function.
        
        Returns:
            The result of the function call.
        """
        ...
    
    def __str__(self) -> str:
        """
        Convert the javascript object to a string.
        """
        ...
    
    def __repr__(self) -> str:
        """
        Convert the javascript object to a string.
        """
        ...
    
    def __len__(self) -> int:
        """
        Get the length of the javascript object.
        """
        ...
    
    def __contains__(self, q: Any) -> bool:
        """
        Check if the javascript object contains a value.
        """
        ...
    
    def __eq__(self, q: Any) -> bool:
        """
        Check if the javascript object is equal to a value.
        """
        ...
    
    def new(self, *args: Any) -> Any:
        """
        Create a new instance of a JavaScript class.
        """
        ...
    
    def __iter__(self) -> Any:
        """
        Get an iterator for the javascript object.
        """
        ...
    
    def __next__(self) -> Any:
        """
        Get the next value from the iterator.
        """
        ...
    
    def __delattr__(self, __name: str) -> None: 
        """
        Delete an attribute from the javascript object.
        """
        ...

    def __delitem__(self, __name: str) -> None:
        """
        Delete an item from the javascript object.
        """
        ...

    def __await__(self) -> Any:
        """
        Wait for the javascript object to resolve.
        """
        ...