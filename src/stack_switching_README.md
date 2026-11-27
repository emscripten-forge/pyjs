The handling of several suspended Python stacks (JSPI, `pyjs.run_sync`) is
adapted from [pyodide](https://github.com/pyodide/pyodide) (release 314.0.8)
and modified to fit pyjs:

- `src/stack_switching.c` (the per-task part of CPython's thread state) is
  based on `src/core/stack_switching/pystate.c` and `pystate_pycore.c`
- `src/js/stack_state.ts` (the C stack data of suspended tasks) is based on
  `src/core/stack_switching/stack_state.mjs`
- the suspend / resume / enter logic in `src/js/jsops.ts` (`jspiAwait`,
  `jspiResume`) and `src/js/pyproxy.ts` (`callPythonPromising`) follows
  `suspenders.c` / `suspenders.mjs` and `callPyObjectKwargsPromising` in
  `src/core/pyproxy.ts`

pyodide is licensed under the Mozilla Public License 2.0, the license text is
in `LICENSE` at the root of this repository. These files are distributed under
the MPL 2.0 as well (each carries the MPL header).
