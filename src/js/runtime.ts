// What a user of pyjs sees on the emscripten `Module` object: starting python
// and running code in it.
//
// Life of a pyjs runtime:
//   1. the embedder creates the emscripten Module (createModule(...))
//   2. the embedder fills the file system (Module.FS) with a python
//      environment: the standard library at /lib/pythonX.Y and packages.
//      pyjs does not do that: where the files come from is the embedder's
//      business (the npm package downloads conda packages, xeus-python has
//      its own way)
//   3. Module.startPython()   <- this file
//   4. Module.exec("...") / Module.runPython("...") / Module.pyimport("...")
import { PYPROXY } from "./codec";
import { suspendedTaskCount } from "./jsops";
import { canRunSync, jspi, jspiEnabled } from "./jspi";
import { stackStateCount } from "./stack_state";
import { PythonError, pyimport, pythonErrorFor, setPythonHelpers } from "./pyproxy";

// from the emscripten runtime this code is embedded in
declare const FS: any;
declare const PATH: any;
declare const LDSO: any;
declare const getDylinkMetadata: any;
declare const loadDynamicLibrary: any;
declare const getPromise: any;
declare const promiseMap: any;
declare const runtimeKeepalivePush: any;
declare const UTF8ToString: any;
declare const stringToUTF8OnStack: any;
declare const wasmTable: any;
declare const specialHTMLTargets: any;

/** copy a JS string into new wasm memory (NUL terminated); the caller frees it */
function cstring(str: string): number {
  const capacity = 3 * str.length + 1; // worst case of utf8, see codec.ts
  const ptr = _malloc(capacity);
  stringToUTF8Array(str, HEAPU8, ptr, capacity);
  return ptr;
}

/** set an environment variable of the wasm program (python reads them at start) */
function setenv(name: string, value: any): void {
  const namePtr = cstring(name);
  const valuePtr = cstring(String(value));
  wasmExports.pyjs_setenv(namePtr, valuePtr);
  _free(namePtr);
  _free(valuePtr);
}

let started = false;

/** the options of runPython / runPythonAsync */
interface RunOptions {
  globals?: any;
  locals?: any;
  filename?: string;
}

/**
 * Start the interpreter (synchronous). The file system must already hold the
 * python environment. Afterwards Module.exec / eval / runPython / pyimport /
 * ... exist. Calling it again does nothing.
 *
 * options: {env: {NAME: value}} extra environment variables
 */
function startPython(options: { env?: Record<string, any> } = {}): void {
  if (started) {
    return;
  }
  // which python this runtime was linked with, e.g. 314 -> "3.14"
  const number = wasmExports.pyjs_python_version();
  const version = `${Math.floor(number / 100)}.${number % 100}`;
  const stdlib = `/lib/python${version}`;
  if (!FS.analyzePath(stdlib).exists) {
    throw new Error(
      `pyjs: the file system has no ${stdlib} (the python standard library): ` +
        "fill the file system before calling startPython()"
    );
  }

  // where python finds itself and its packages
  const sitePackages = `${stdlib}/site-packages`;
  setenv("LANG", "en_US.UTF-8");
  setenv("PYTHONHOME", "/");
  setenv("PYTHONPATH", `${sitePackages}:/usr/lib/python${version}/site-packages`);
  FS.mkdirTree(sitePackages);
  for (const [name, value] of Object.entries(options.env ?? {})) {
    setenv(name, value);
  }

  if (wasmExports.pyjs_start_python() !== 0) {
    throw new Error("pyjs: the python interpreter did not start");
  }
  bindPython();
  // Python is entered from JS events (timers, promises, ...) from now on.
  // Without this emscripten would shut the runtime down when it thinks the
  // program is over.
  runtimeKeepalivePush();
  started = true;
}

/**
 * Right after python started: import the python package `pyjs` and build
 * the JavaScript API that calls into Python. Afterwards these exist on the
 * Module (the object users get from initializePyjsRuntime / createModule):
 *
 *   Module.globals         the namespace code runs in by default (the dict of
 *                          `__main__`), names of `builtins` found too
 *   Module.runPython       run Python code, return the value of its last line
 *   Module.runPythonAsync  the same with top-level `await`, returns a promise
 *   Module.pyimport        `import name`, the module as PyProxy
 *   Module.toPy            a JS value as Python object (python's to_py)
 *
 * and the JS side of the core gets the Python helpers it needs
 * (setPythonHelpers: `then` of awaitables, PyProxy.toJs, generator steps).
 * Each of these functions is a thin wrapper: the work is done by Python
 * functions (mostly module/pyjs/code.py), called through PyProxies.
 */
function bindPython(): void {
  // (importing it also sets up the python side of the core, see
  // module/pyjs/__init__.py)
  const pyjs = pyimport("pyjs");

  // The namespace code runs in by default: the globals of the module
  // __main__, as when running a script. A PyProxy of that dict.
  const main = pyimport("__main__");
  const scope = main.__dict__;
  main.destroy();

  // Module.globals: that dict, with one addition. Python finds names that
  // are not in the globals in the module `builtins` (`open`, `len`, ...).
  // `Module.globals.get("open")` shall find them too (as in pyodide), so
  // get() and has() look there second. Everything else goes to the dict.
  const builtinsModule = pyimport("builtins");
  const builtins = builtinsModule.__dict__;
  builtinsModule.destroy();
  Module.globals = new Proxy(scope, {
    get(target, property) {
      if (property === "get") {
        return (key: any) => {
          const value = target.get(key);
          return value === undefined ? builtins.get(key) : value;
        };
      }
      if (property === "has") {
        return (key: any) => target.has(key) || builtins.has(key);
      }
      return Reflect.get(target, property);
    },
  });

  // The python module with the functions doing the actual work
  // (module/pyjs/code.py). They are looked up in it on every call, not
  // fetched once: python code may replace them (`pyjs.code.eval_code = ...`)
  // to change what runPython does.
  const code = pyjs.code;
  const toPy = pyjs.to_py;
  setPythonHelpers(pyjs._then, pyjs.to_js, pyjs.core._generator_step);
  pyjs.destroy();

  /**
   * A JS value as Python object (python's `pyjs.to_py`): an Array becomes a
   * list, a Map / plain Object a dict, ... The result is a PyProxy (values
   * that need no proxy, like numbers, come back as they are).
   * options: {depth, defaultConverter} as for `to_py` in python.
   */
  Module.toPy = function (value: any, options: { depth?: number; defaultConverter?: any } = {}): any {
    const kwargs: Record<string, any> = { depth: options.depth ?? -1 };
    if (options.defaultConverter !== undefined) {
      kwargs.default_converter = options.defaultConverter;
    }
    return toPy.callKwargs(value, kwargs);
  };

  /**
   * Run python code and return the value of its last line, if that is an
   * expression (like a notebook cell): `runPython("x = 20\nx + 1")` is 21.
   * options: {globals, locals} the namespaces to run in (PyProxies of
   * dicts); default: Module.globals. {filename}: the file name in
   * tracebacks (default "<exec>").
   */
  Module.runPython = function (source: string, options: RunOptions = {}): any {
    const globals = options.globals ?? scope;
    const locals = options.locals ?? globals;
    // (the filename only when given: a replacement of eval_code, see above,
    // may not take it)
    return options.filename === undefined
      ? code.eval_code(source, globals, locals)
      : code.eval_code.callKwargs(source, globals, locals, { filename: options.filename });
  };

  /** like runPython, for code that uses `await` at the top level; returns a promise */
  Module.runPythonAsync = async function (source: string, options: RunOptions = {}): Promise<any> {
    const globals = options.globals ?? scope;
    // `eval_code_async` is an `async def` function: calling it starts the
    // code as asyncio task (see `call` in src/py_entry.cpp) and gives that
    // task as PyProxy. Awaiting the proxy waits for its result.
    const locals = options.locals ?? globals;
    const task =
      options.filename === undefined
        ? code.eval_code_async(source, globals, locals)
        : code.eval_code_async.callKwargs(source, globals, locals, { filename: options.filename });
    try {
      return await task;
    } finally {
      task.destroy();
    }
  };

  /**
   * `import name`: the python module as PyProxy. A dotted name whose last
   * part is no module gives that attribute (`pyimport("os.path.join")`).
   */
  Module.pyimport = (name: string) => code._pyimport(name);
}

/** what exists on Module before python is started */
export function installModuleApi(): void {
  Module.startPython = startPython;
  Module.setenv = setenv;
  Module.PythonError = PythonError;

  // where this runtime runs
  Module._IS_NODE = typeof process === "object" && typeof require === "function";
  Module._IS_BROWSER_WORKER_THREAD = typeof importScripts === "function";
  Module._IS_BROWSER_MAIN_THREAD = typeof window === "object";

  // small helpers the python package calls (things python cannot express:
  // `None` stands for both undefined and a missing value)
  Module._is_undefined = (value: any) => value === undefined;
  Module._is_null = (value: any) => value === null;
  // JSDoubleProxy.unwrap(): a copy of the PyProxy `p` that comes back to
  // python as the Python object itself (not as proxy, see encode in
  // codec.ts). The copy is released by the garbage collector.
  Module._unwrap_double_proxy = (p: any) => {
    const copy = p.copy();
    copy[PYPROXY].roundtrip = false;
    return copy;
  };
  // the JS error standing for a Python exception (see pythonErrorFor)
  Module._python_error = pythonErrorFor;
  // is `value` such an error (a Python exception travelling through JS)?
  Module._is_python_error = (value: any) => value instanceof PythonError && value.__pyjs_exception !== 0;
  // throws its argument. Called from python with a PythonError, this raises
  // the Python exception inside it (see `fail` in jsops.ts).
  Module._throw = (value: any) => {
    throw value;
  };

  // JSPI, see jspi.ts
  Module._jspi_enabled = jspiEnabled;
  Module._jspi_can_run_sync = canRunSync;
  /** switch JSPI off: pyjs then behaves like in a browser without it (tests) */
  Module._jspi_disable = () => {
    jspi.disabled = true;
  };
  /**
   * for tests: how many Python call stacks are suspended in run_sync, and how
   * many of them have data on the C stack (see stack_state.ts)
   */
  Module._jspi_suspended_count = suspendedTaskCount;
  Module._jspi_stack_state_count = stackStateCount;

  /**
   * make `canvas` (HTMLCanvasElement or OffscreenCanvas) the canvas
   * emscripten's GL / SDL / html5 code renders to: `Module.canvas` (SDL2) and
   * the "#canvas" target (emscripten_webgl_create_context("#canvas"), events)
   */
  Module._set_canvas = (canvas: any) => {
    Module.canvas = canvas;
    if (typeof specialHTMLTargets !== "undefined") {
      specialHTMLTargets["#canvas"] = canvas;
    }
  };

  // Parts of the emscripten runtime embedders need (to fill the file system,
  // load shared libraries, ...). Defined as getters because this code runs
  // while the runtime script is still being set up: some of these do not
  // exist yet at this point, but do when somebody asks for them.
  const lazy: Record<string, () => any> = {
    FS: () => FS,
    PATH: () => PATH,
    LDSO: () => LDSO,
    getDylinkMetadata: () => getDylinkMetadata,
    loadDynamicLibrary: () => loadDynamicLibrary,
    getPromise: () => getPromise,
    promiseMap: () => promiseMap,
    stackSave: () => stackSave,
    stackRestore: () => stackRestore,
    runtimeKeepalivePush: () => runtimeKeepalivePush,
    UTF8ToString: () => UTF8ToString,
    stringToUTF8OnStack: () => stringToUTF8OnStack,
    wasmTable: () => wasmTable,
  };
  for (const [name, get] of Object.entries(lazy)) {
    if (!(name in Module)) {
      Object.defineProperty(Module, name, { get, configurable: true, enumerable: true });
    }
  }
}

// (names of the surrounding script this file only probes with `typeof`)
declare const process: any;
declare const require: any;
declare const importScripts: any;
declare const window: any;
