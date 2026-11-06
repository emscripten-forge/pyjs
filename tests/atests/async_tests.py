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


async def test_js_webgpu():

    has_webgpu = pyjs.to_py(
        pyjs.js.Function(
            "return typeof navigator !== 'undefined' && navigator.gpu !== undefined"
        )()
    )
    assert has_webgpu, "this browser does not expose navigator.gpu"

    async_js_function = pyjs.js.Function(
        """
        return async function(){
            const format = navigator.gpu.getPreferredCanvasFormat()
            const adapter = await navigator.gpu.requestAdapter()
            if (adapter === null){
                return {status: "no adapter", format: format}
            }
            const device = await adapter.requestDevice()
            if (device === null){
                return {status: "no device", format: format}
            }
            return {
                status: "ok",
                format: format,
                maxComputeWorkgroupSizeX: device.limits.maxComputeWorkgroupSizeX,
            }
        }
    """
    )()

    result = pyjs.to_py(await async_js_function())

    # no adapter needed to query the preferred canvas format
    assert result["format"] in ("bgra8unorm", "rgba8unorm")

    if result["status"] != "ok":
        print(f"skip adapter/device part of the browser webgpu test: {result['status']}")
        return

    assert result["maxComputeWorkgroupSizeX"] >= 1


async def trigger_js_tests():

    js_test_path = Path(__file__).parents[1] / "jtests" / "test_main.js"
    with open(js_test_path) as f:
        content = f.read()
    js_tests_async_main = pyjs.js.Function(content)()

    js_tests_return_code = await js_tests_async_main()
    assert js_tests_return_code == 0

