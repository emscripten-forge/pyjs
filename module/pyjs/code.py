"""Running code: JavaScript from Python (`run_js`), and Python source given as
text (`eval_code`, `eval_code_async`; these are what `runPython` /
`runPythonAsync` in JavaScript call). The names are pyodide's
(``pyodide.code``); `run_js` is also in PEP 818 (``jstypes.code``)."""

import ast
import inspect

import pyjs_core

__all__ = ["run_js", "eval_code", "eval_code_async"]

# The global `eval`, fetched once. Calling `eval` through a reference like
# this (not as `eval(...)` written in the code) is an "indirect eval": the
# code runs in the global scope, not inside some function of pyjs.
_eval = pyjs_core.global_this().eval


def run_js(code):
    """Evaluate JavaScript `code` in the global scope and return the value of
    its last expression.

    Example:
    ```python
    assert run_js("1 + 2") == 3
    add = run_js("(a, b) => a + b")
    assert add(1, 2) == 3
    ```
    """
    return _eval(code)


def _split_last_expression(source):
    """Parse `source` and split it into (the statements to execute, the last
    expression to evaluate). Either part can be None.

    Why: `exec` runs statements but returns nothing, `eval` returns a value
    but only accepts one expression. To run a whole script AND get the value
    of its last line (like a notebook cell does) the script is cut in two:
    everything before the last line is executed, the last line is evaluated,
    provided it is an expression (`x + 1`) and not a statement (`x = 1`).
    """
    body = ast.parse(source).body
    if not body:
        return None, None
    if isinstance(body[-1], ast.Expr):
        statements = ast.Module(body=body[:-1], type_ignores=[]) if len(body) > 1 else None
        return statements, ast.Expression(body=body[-1].value)
    return ast.Module(body=body, type_ignores=[]), None


def eval_code(source, globals=None, locals=None):
    """Run Python `source` and return the value of its last expression (None
    if it ends with a statement).

    Args:
        source: the code, any number of lines.
        globals / locals: the namespaces to run in, as for `exec`.

    Example:
    ```python
    assert eval_code("x = 20\\nx + 1") == 21
    ```
    """
    statements, expression = _split_last_expression(source)
    if statements is not None:
        exec(compile(statements, "<exec>", "exec"), globals, locals)
    if expression is not None:
        return eval(compile(expression, "<exec>", "eval"), globals, locals)
    return None


async def eval_code_async(source, globals=None, locals=None):
    """Like `eval_code`, for code that uses ``await`` at the top level.

    The code runs with module level semantics (like the asyncio REPL and
    IPython): assignments go to `globals`, each statement runs exactly once.
    """
    # lets the compiler accept `await` outside of a function
    flags = ast.PyCF_ALLOW_TOP_LEVEL_AWAIT

    async def run(code):
        """run compiled code; if it contained an await, wait for it"""
        result = eval(code, globals, locals)
        # Code compiled with the flag above that really contains an `await`
        # is a coroutine: evaluating it only creates the coroutine, which
        # then has to be awaited to actually run.
        if code.co_flags & inspect.CO_COROUTINE:
            result = await result
        return result

    statements, expression = _split_last_expression(source)
    if statements is not None:
        await run(compile(statements, "<exec>", "exec", flags=flags))
    if expression is not None:
        return await run(compile(expression, "<exec>", "eval", flags=flags))
    return None
