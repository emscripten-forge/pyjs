import pyjs
from pathlib import Path
import json
import io
import tarfile 

async def test_stuff():
    assert 2 == 2


async def test_stuff_2():
    assert 2 == 2


async def test_callbacks_in_async_1():
    def py_func(arg1, arg2):
        return arg1 * 2 + arg2

    js_func, cleanup = pyjs.create_callable(py_func)

    async_js_function = pyjs.js.Function(
        """
        return async function(callback, arg){
            let res =  callback(arg * 2, 42);
            return res
        }
    """
    )()

    result = await async_js_function(js_func, 42)
    assert result == 42 * 2 * 2 + 42
    cleanup.delete()


async def test_callbacks_in_async_2():

    async_js_function = pyjs.js.Function(
        """
        return async function(py_dict){
            return py_dict.get('value')
        }
    """
    )()

    pyval = {"value": 42}
    result = await async_js_function(pyval)
    assert result == 42
