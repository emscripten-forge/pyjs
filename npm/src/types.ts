/**
 * Types of the pyjs runtime (the emscripten `Module` with the functions added
 * by `include/pyjs/pre_js/*.js` / `post_js/*.js`) and of its initialization.
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

/** A conda package (`.conda` / `.tar.bz2`, e.g. from emscripten-forge) by URL. */
export interface IPinnedPackage {
  /** URL of the package file; name / version / build are taken from its file name */
  url: string;
  /** checked only with `verifySha256: true` */
  sha256?: string;
}

/**
 * An archive unpacked into the emscripten file system: tar or zip,
 * optionally compressed with gzip, bzip2 or zstd (detected from the content).
 */
export interface IArchive {
  /** URL of the archive (relative URLs resolve against the page) */
  url: string | URL;
  /** directory the archive is unpacked into (created if needed), e.g. `/examples` */
  path: string;
  /** checked only with `verifySha256: true` */
  sha256?: string;
  /**
   * cache the archive like a package (default: false): its unpacked files
   * and python's bytecode of its `.py` files, by URL + `path`. Only for
   * URLs whose content never changes (e.g. a content hash in the file
   * name): a cached archive is not downloaded again
   */
  cache?: boolean;
}

/** A file written into the emscripten file system: its content or a URL. */
export interface IFile {
  /** absolute path in the file system, e.g. `/data/config.json` */
  path: string;
  /** the content (a string is written as UTF-8) */
  data?: Uint8Array | string;
  /** or: fetched from this URL */
  url?: string | URL;
}

/** What `onProgress` reports. */
export interface IProgress {
  /** a package name, an archive / file URL, or "python" */
  item: string;
  /**
   * solve: solving the package specs; download: bytes arriving (`done` /
   * `total`, total 0 if unknown); cached: taken from the package cache;
   * extract: written into the file system; link: shared libraries loaded;
   * start: python starts
   */
  phase: "solve" | "download" | "cached" | "extract" | "link" | "start";
  done: number;
  total: number;
}

/** Options of `installPackages` (after the runtime started). */
export interface IInstallOptions {
  /** channels to solve specs against (default: the channels of `initializePyjsRuntime`) */
  channels?: string[];
  /** receives the solver output */
  logger?: ILogger;
  /** shortcut for `logger: console` */
  verbose?: boolean;
  /** progress of this install (default: the `onProgress` of `initializePyjsRuntime`) */
  onProgress?: (progress: IProgress) => void;
  /** check sha256 values (default: the `verifySha256` of `initializePyjsRuntime`) */
  verifySha256?: boolean;
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
   * Start python on the filled file system (already done by
   * `initializePyjsRuntime`; for embedders filling the file system themselves).
   */
  startPython(options?: { env?: Record<string, string> }): void;

  /**
   * Install conda packages into the running runtime: specs (solved, e.g.
   * `["numpy", "pandas>=2"]`) or pinned packages (`[{url}]`, no solver).
   * Returns the names of the packages that were installed.
   */
  installPackages(packages: string[] | (string | IPinnedPackage)[], options?: IInstallOptions): Promise<string[]>;

  /**
   * Fetch an archive and unpack it into the file system below `archive.path`,
   * e.g. `await pyjs.unpackArchive({ url: "examples.tar.gz", path: "/examples" })`.
   * Returns the absolute paths of the written files.
   */
  unpackArchive(archive: IArchive): Promise<string[]>;

  /** write files into the file system (content or URL) */
  addFiles(files: IFile[]): Promise<void>;

  /**
   * save the bytecode python wrote since the last save (packages, the python
   * environment, archives with `cache: true`) to the bytecode cache. Call it
   * once the imports are done (await it before a reload). Besides, it is only
   * tried when the page becomes hidden (best effort, main thread only):
   * nothing saves periodically. A no-op without the cache
   */
  saveBytecode(): Promise<void>;

  /**
   * where the initialization spent its time (ms): `total`, `assets`,
   * `waitRuntime` (wasm instantiation), `waitDownloads`, `waitSolve`,
   * `extractEnv`, `extractPackages`, `link` (shared libraries), `start` (python)
   */
  readonly initTimings: Readonly<Record<string, number>>;

  /**
   * the same for the last `installPackages` call (ms): `total`, `solve`,
   * `waitDownloads`, `extractPackages`, `link` (shared libraries),
   * `invalidateCaches`; undefined before the first one
   */
  readonly installTimings?: Readonly<Record<string, number>>;

  /**
   * the architecture of this runtime: `"wasm32"` or `"wasm64"`, given by the
   * entry it was loaded from (`.` / `./wasm32` or `./wasm64`)
   */
  readonly pyjsArch: "wasm32" | "wasm64";
  /** python version of the runtime, e.g. `[3, 14, 3]` */
  readonly pythonVersion: number[];

  [key: string]: any;
}

/** Where the runtime files are (`initializePyjsRuntime`, `compileRuntime`). */
export interface IAssetsOptions {
  /**
   * URL of a self-hosted copy of the package's `assets/` directory
   * (`npx <package> copy-assets <dir>`: `wasm32/`, `wasm64/` with the runtime +
   * packed python environment).
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
}

export interface IInitializeOptions extends IAssetsOptions {
  /**
   * conda package specs installed before python starts, e.g. `["numpy>=2"]`;
   * solved (mambajs) while the runtime is instantiated
   */
  packages?: string[];
  /**
   * pinned conda packages installed before python starts (no solver), e.g.
   * from `npx <package> lock` (`lock.wasm32`)
   */
  urls?: (string | IPinnedPackage)[];
  /**
   * archives unpacked into the file system before python starts (after the
   * packages: they can override files), see `PyjsModule.unpackArchive`
   */
  archives?: IArchive[];
  /** files written into the file system before python starts (after the archives) */
  files?: IFile[];
  /**
   * conda channels the specs are solved against
   * (default: emscripten-forge 6x + conda-forge)
   */
  channels?: string[];
  /**
   * Preload the shared libraries of the packages (default: true in the main
   * thread, false in a worker: there `dlopen` can compile synchronously)
   */
  preloadSharedLibs?: boolean;
  /**
   * cache installed conda packages in Cache Storage, by URL (package URLs are
   * immutable), as their final layout: a later install only untars.
   * true (default, cache "pyjs-packages-v2"), false, or a cache name
   */
  cache?: boolean | string;
  /**
   * keep python's bytecode (`__pycache__/*.pyc`) of the packages and the
   * python environment in Cache Storage ("<cache name>-bytecode"), so imports
   * on the next visit do not compile the sources again (default: true when
   * `cache` is on); restored automatically, saved by `PyjsModule.saveBytecode`
   */
  bytecodeCache?: boolean;
  /** check the sha256 of packages / archives that have one (default: false) */
  verifySha256?: boolean;
  /** progress of downloads, extraction, linking, start */
  onProgress?: (progress: IProgress) => void;
  /**
   * the runtime wasm, compiled already (`compileRuntime()`, e.g. once in the
   * main thread and posted to several workers)
   */
  wasmModule?: WebAssembly.Module;
  /** extra environment variables of python */
  env?: Record<string, string>;
  /** stdout of python / the runtime (default: console.log) */
  print?: (text: string) => void;
  /** stderr of python / the runtime (default: console.warn) */
  printErr?: (text: string) => void;
  /** solver messages (default: none, `console` if `verbose`) */
  logger?: ILogger;
  verbose?: boolean;
  /** extra properties for the emscripten Module (advanced) */
  moduleOptions?: Record<string, unknown>;
}
