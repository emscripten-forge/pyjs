import pyjs
from pathlib import Path
import json
import io
import tarfile 

async def test_stuff():
    assert 2 == 2


async def test_stuff_2():
    assert 2 == 2


async def test_callbacks_in_async():
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


async def test_callbacks_in_async():

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


async def trigger_js_tests():

    js_test_path = Path(__file__).parents[1] / "jtests" / "test_main.js"
    with open(js_test_path) as f:
        content = f.read()
    js_tests_async_main = pyjs.js.Function(content)()

    js_tests_return_code = await js_tests_async_main()
    assert js_tests_return_code == 0



if pyjs.IN_BROWSER:
    async def test_parallel_fetch_bytes():
        print("IN THAT TWEST")
        url = "./sample.json.tar.bz2"
        response = await pyjs.js.fetch(url)
        assert bool(response.ok)
        array_buffer = await response.arrayBuffer()
        pyjs.js.console.log(array_buffer)
        array = pyjs.to_py(array_buffer)
        byteio = io.BytesIO(array)

        tar = tarfile.open(fileobj=byteio, mode="r")
        jfile = tar.extractfile("sample.json")
        j = json.load(jfile)
        assert j["hello"] == "world"
    # async def test_parallel_fetch_tarfiles():

    #     url = "./sample.json.tar.bz2"
    #     tarfile = (await pyjs.parallel_fetch_tarfiles(url))[0]
       
    #     result = tarfile.extractfile("sample.json")
    #     json.loads(result.read())