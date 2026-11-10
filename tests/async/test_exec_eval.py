"""pyjs.async_exec_eval (used by `Module.async_exec_eval`): top level await with
module level semantics, every statement runs exactly once."""

import pyjs


def _scope():
    return {"__name__": "__exec_eval_test__"}


async def test_async_exec_eval_last_expression_runs_once():
    scope = _scope()
    scope["calls"] = []
    result = await pyjs.async_exec_eval("calls.append(1)\ncalls.append(2) or len(calls)", scope)
    assert scope["calls"] == [1, 2], scope["calls"]
    assert result == 2


async def test_async_exec_eval_assignments_go_to_globals():
    scope = _scope()
    await pyjs.async_exec_eval("n = 1", scope)
    await pyjs.async_exec_eval("n += 1", scope)
    assert scope["n"] == 2
    assert await pyjs.async_exec_eval("n * 21", scope) == 42


async def test_async_exec_eval_top_level_await():
    scope = _scope()
    result = await pyjs.async_exec_eval(
        "import asyncio\nawait asyncio.sleep(0)\nx = await asyncio.sleep(0, result=20)\nx * 2 + 2",
        scope,
    )
    assert result == 42
    assert scope["x"] == 20
    # await in the last expression
    assert await pyjs.async_exec_eval("await asyncio.sleep(0, result='last')", scope) == "last"


async def test_async_exec_eval_await_js_promise():
    scope = _scope()
    result = await pyjs.async_exec_eval(
        "from pyjs import js\nawait js.Promise.resolve(41) + 1", scope
    )
    assert result == 42


async def test_async_exec_eval_no_expression_returns_none():
    scope = _scope()
    assert await pyjs.async_exec_eval("y = 3", scope) is None
    assert await pyjs.async_exec_eval("", scope) is None
    assert scope["y"] == 3


async def test_async_exec_eval_functions_and_loops():
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
    assert await pyjs.async_exec_eval(code, scope) == 6


async def test_async_exec_eval_raises():
    scope = _scope()
    try:
        await pyjs.async_exec_eval("import asyncio\nawait asyncio.sleep(0)\nraise ValueError('boom')", scope)
    except ValueError as e:
        assert "boom" in str(e)
    else:
        raise AssertionError("expected ValueError")


async def test_exec_eval_last_expression_runs_once():
    scope = _scope()
    scope["calls"] = []
    assert pyjs.exec_eval("calls.append(1)\ncalls.append(2) or len(calls)", scope) == 2
    assert scope["calls"] == [1, 2]
