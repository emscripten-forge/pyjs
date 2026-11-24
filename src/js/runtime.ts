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
import { canRunSync, jspi, jspiEnabled } from "./jspi";
import { PythonError, pyimport, setPythonHelpers } from "./pyproxy";

// from the emscripten runtime this code is embedded in
declare const FS: any;
declare const PATH: any;
declare const LDSO: any;
declare const getDylinkMetadata: any;
declare const loadDynamicLibrary: any;
declare const getPromise: any;
declare const promiseMap: any;
declare const stackSave: any;
declare const stackRestore: any;
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

/** import the python package `pyjs` and build the JS functions that call into it */
function bindPython(): void {
  // (importing it also sets up the python side of the core, see
  // module/pyjs/__init__.py)
  const pyjs = pyimport("pyjs");

  // The namespace code runs in by default: the globals of the module
  // __main__, as when running a script. A PyProxy of that dict.
  const main = pyimport("__main__");
  const scope = main.__dict__;
  main.destroy();
  Module.globals = scope;

  // the python functions doing the actual work (module/pyjs/code.py)
  const evalCode = pyjs.eval_code;
  const evalCodeAsync = pyjs.eval_code_async;
  setPythonHelpers(pyjs._then, pyjs.to_js);
  pyjs.destroy();

  /**
   * Run python code and return the value of its last line, if that is an
   * expression (like a notebook cell): `runPython("x = 20\nx + 1")` is 21.
   * options: {globals, locals} the namespaces to run in (PyProxies of
   * dicts); default: Module.globals.
   */
  Module.runPython = function (code: string, options: { globals?: any; locals?: any } = {}): any {
    const globals = options.globals ?? scope;
    return evalCode(code, globals, options.locals ?? globals);
  };

  /** like runPython, for code that uses `await` at the top level; returns a promise */
  Module.runPythonAsync = async function (
    code: string,
    options: { globals?: any; locals?: any } = {}
  ): Promise<any> {
    const globals = options.globals ?? scope;
    // Calling an `async def` function does not run it yet: it gives a
    // coroutine, here as PyProxy. Awaiting that proxy runs the code (as
    // asyncio task) and waits for its result.
    const coroutine = evalCodeAsync(code, globals, options.locals ?? globals);
    try {
      return await coroutine;
    } finally {
      coroutine.destroy();
    }
  };

  /** `import name`: the python module as PyProxy */
  Module.pyimport = pyimport;
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

  // JSPI, see jspi.ts
  Module._jspi_enabled = jspiEnabled;
  Module._jspi_can_run_sync = canRunSync;
  /** switch JSPI off: pyjs then behaves like in a browser without it (tests) */
  Module._jspi_disable = () => {
    jspi.disabled = true;
  };

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
