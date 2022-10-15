from pathlib import Path
import pyjs


async def main():

    js_test_path = Path(__file__).parents[1] / "js_tests" / "test_main.js"
    with open(js_test_path) as f:
        content = f.read()
    js_tests_async_main = pyjs.js.Function(content)()

    js_pyjs = pyjs.js.pyjs
    js_tests_return_code = await js_tests_async_main(js_pyjs)
    return js_tests_return_code
