`webloop.py` is adapted from [pyodide](https://github.com/pyodide/pyodide) and
modified to fit pyjs:

- `WebLoop` is based on
  [`src/py/pyodide/webloop.py`](https://github.com/pyodide/pyodide/blob/main/src/py/pyodide/webloop.py)
- `_MacrotaskQueue` (zero-delay scheduling for `WebLoop.call_soon`) is based on
  [`src/js/scheduler.ts`](https://github.com/pyodide/pyodide/blob/main/src/js/scheduler.ts)

pyodide is licensed under the Mozilla Public License 2.0, see `webloop_LICENSE`.
`webloop.py` is therefore distributed under the MPL 2.0 as well.
