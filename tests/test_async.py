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

    async_js_function = pyjs.js.Function(
        """
        return async function(callback, arg){
            // (after an await: the call that passed `callback` has returned)
            await null;
            let res =  callback(arg * 2, 42);
            return res
        }
    """
    )()

    # a lasting proxy, destroyed by hand ...
    js_func = pyjs.create_proxy(py_func)
    result = await async_js_function(js_func, 42)
    assert result == 42 * 2 * 2 + 42
    js_func.destroy()

    # ... and the plain function: its proxy lives until the promise the
    # async JS function returned settles
    result = await async_js_function(py_func, 42)
    assert result == 42 * 2 * 2 + 42


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
