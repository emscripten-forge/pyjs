"""pyjs.eval_code / pyjs.eval_code_async (what `runPython` / `runPythonAsync`
in JavaScript call): the value of the last expression, top level await with
module level semantics, every statement runs exactly once."""

import pyjs


def _scope():
    """a fresh namespace to run code in"""
    return {"__name__": "__eval_code_test__"}


async def test_eval_code_async_last_expression_runs_once():
    scope = _scope()
    scope["calls"] = []
    result = await pyjs.eval_code_async("calls.append(1)\ncalls.append(2) or len(calls)", scope)
    assert scope["calls"] == [1, 2], scope["calls"]
    assert result == 2


async def test_eval_code_async_assignments_go_to_globals():
    scope = _scope()
    await pyjs.eval_code_async("n = 1", scope)
    await pyjs.eval_code_async("n += 1", scope)
    assert scope["n"] == 2
    assert await pyjs.eval_code_async("n * 21", scope) == 42


async def test_eval_code_async_top_level_await():
    scope = _scope()
    result = await pyjs.eval_code_async(
        "import asyncio\nawait asyncio.sleep(0)\nx = await asyncio.sleep(0, result=20)\nx * 2 + 2",
        scope,
    )
    assert result == 42
    assert scope["x"] == 20
    # await in the last expression
    assert await pyjs.eval_code_async("await asyncio.sleep(0, result='last')", scope) == "last"


async def test_eval_code_async_await_js_promise():
    scope = _scope()
    result = await pyjs.eval_code_async("import js\nawait js.Promise.resolve(41) + 1", scope)
    assert result == 42


async def test_eval_code_async_no_expression_returns_none():
    scope = _scope()
    assert await pyjs.eval_code_async("y = 3", scope) is None
    assert await pyjs.eval_code_async("", scope) is None
    assert scope["y"] == 3


async def test_eval_code_async_functions_and_loops():
    scope = _scope()
    code = """
import asyncio

async def twice(v):
    await asyncio.sleep(0)
    return 2 * v

total = 0
for i in range(3):
    total += await twice(i)
total
"""
    assert await pyjs.eval_code_async(code, scope) == 6


async def test_eval_code_async_raises():
    scope = _scope()
    try:
        await pyjs.eval_code_async("import asyncio\nawait asyncio.sleep(0)\nraise ValueError('boom')", scope)
    except ValueError as e:
        assert "boom" in str(e)
    else:
        raise AssertionError("expected ValueError")


async def test_eval_code_last_expression_runs_once():
    scope = _scope()
    scope["calls"] = []
    assert pyjs.eval_code("calls.append(1)\ncalls.append(2) or len(calls)", scope) == 2
    assert scope["calls"] == [1, 2]


async def test_eval_code_no_expression_returns_none():
    scope = _scope()
    assert pyjs.eval_code("y = 3", scope) is None
    assert pyjs.eval_code("", scope) is None
    assert pyjs.eval_code("y", scope) == 3


async def test_eval_code_pyodide_names():
    # the same functions under pyodide's module name
    from pyodide.code import eval_code, eval_code_async

    assert eval_code is pyjs.eval_code
    assert eval_code_async is pyjs.eval_code_async
