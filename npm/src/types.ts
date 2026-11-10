/**
 * Types of the pyjs runtime (the emscripten `Module` with the functions added
 * by `include/pyjs/pre_js/*.js` / `post_js/*.js`).
 *
 * Only the public, stable part is typed; everything else on the Module is
 * still there (`[key: string]: any`).
 */

/** A python object living in the wasm heap (embind class `pyobject`). */
export interface PyObject {
  /** call the python object, positional arguments only */
  py_call(...args: unknown[]): any;
  /** call the python object with positional and keyword arguments */
  py_apply(args?: unknown[], kwargs?: Record<string, unknown>): any;
  /** `obj[key]` / `obj[k1, k2]` */
  get(...keys: unknown[]): any;
  /** free the python reference held by this JS object */
  delete(): void;
  [key: string]: any;
}

export interface ILogger {
  log(...msg: any[]): void;
  warn(...msg: any[]): void;
  error(...msg: any[]): void;
}

/** The initialized pyjs runtime. */
export interface PyjsModule {
  /** execute python code (statements), throws on python errors */
  exec(code: string, globals?: PyObject, locals?: PyObject): void;
  /** evaluate a python expression and return its value (converted to JS) */
  eval(code: string, globals?: PyObject, locals?: PyObject): any;
  /** execute a script and return the value of its last expression */
  exec_eval(script: string, globals?: PyObject, locals?: PyObject): any;
  /** like `exec_eval`, the script may use top level `await` */
  async_exec_eval(script: string, globals?: PyObject, locals?: PyObject): Promise<any>;
  /** execute a python file from the emscripten file system */
  eval_file(path: string, globals?: PyObject, locals?: PyObject): void;
  /** convert a python object to a JS value (`pyjs.to_js`) */
  to_js(obj: PyObject): any;
  /** the `__main__` scope used as default globals */
  default_scope: PyObject;
  /** the python module `pyjs` */
  py_pyjs: PyObject;
  /** the emscripten file system */
  FS: any;

  /**
   * Solve and install conda packages (from `channels`) into the running
   * runtime, e.g. `await pyjs.installPackages(["numpy", "pandas>=2"])`.
   * Packages already installed are kept; returns the names of the packages
   * that were installed.
   */
  installPackages(specs: string[], options?: IInstallOptions): Promise<string[]>;

  /** the target architecture of this runtime */
  readonly pyjsArch: "wasm32" | "wasm64";
  /** python version of the runtime, e.g. `[3, 14, 3]` */
  readonly pythonVersion: number[];

  [key: string]: any;
}

export interface IInstallOptions {
  /** channels to solve against (default: the channels of `initializePyjsRuntime`) */
  channels?: string[];
  /** receives the mambajs output (solver, package table) */
  logger?: ILogger;
  /** shortcut for `logger: console` */
  verbose?: boolean;
}

export interface IInitializeOptions {
  /** conda packages installed before the interpreter starts, e.g. `["numpy>=2"]` */
  extraPackages?: string[];
  /** alias of `extraPackages` */
  extra_packages?: string[];
  /**
   * conda channels used for `extraPackages` / `installPackages`
   * (default: emscripten-forge 6x + conda-forge)
   */
  channels?: string[];
  /**
   * URL of a self-hosted copy of the package's `assets/` directory
   * (`npx <package> copy-assets <dir>`: `untarjs.wasm`, `wasm32/`, `wasm64/`
   * with the runtime + packed python environment).
   * Default: `assets/` next to the module; if it is not there (bundled
   * apps) the CDN (`cdnUrl`), unless `cdnFallback` is false.
   */
  assetsUrl?: string | URL;
  /**
   * where the assets are loaded from when they are not next to the module
   * (default: jsDelivr, exactly this package version)
   */
  cdnUrl?: string;
  /** load the assets from `cdnUrl` when they are not next to the module (default: true) */
  cdnFallback?: boolean;
  /**
   * Preload the shared libraries of installed packages (default: true in the
   * main thread, false in a worker: there `dlopen` can compile synchronously)
   */
  preloadSharedLibs?: boolean;
  /** stdout of python / the runtime (default: console.log) */
  print?: (text: string) => void;
  /** stderr of python / the runtime (default: console.warn) */
  printErr?: (text: string) => void;
  /** progress / solver messages (default: none, `console` if `verbose`) */
  logger?: ILogger;
  verbose?: boolean;
  /** extra properties for the emscripten Module (advanced) */
  moduleOptions?: Record<string, unknown>;
}
