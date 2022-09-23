import pyjs


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
