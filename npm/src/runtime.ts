/**
 * Initialization of the pyjs runtime, shared by the wasm32 and the wasm64 entry.
 *
 * Everything that can run in parallel does: instantiating the runtime wasm,
 * solving package specs (mambajs, loaded lazily), downloading the shipped
 * python environment, the pinned / solved packages and the archives. Then the
 * downloads are extracted into the file system in a fixed order (environment,
 * packages, archives, files) by the runtime's own extractor (libarchive, see
 * src/extract.cpp), shared libraries are preloaded in the main thread, and
 * python starts (`Module.startPython`).
 */
import { cacheNameOf, fetchBytes, readExtracted, storeExtracted } from "./fetch";
import {
  extractArchive,
  installCondaPackage,
  installExtracted,
  parsePinned,
  removeFiles,
  writeFile,
  type IExtractedPackage,
  type IInstalled,
  type IPackageRef,
} from "./install";
import { BytecodeCache, bytecodeCacheName } from "./bytecode";
import { preloadSharedLibs } from "./sharedlibs";
import { lockEntryOfPinned, PROTECTED_PACKAGES, solveSpecs } from "./solve";
import { DEFAULT_CHANNELS, PACKAGE_NAME, DEFAULT_CDN_URL } from "./constants";
// a plain (unminified, not bundled by us) module: keeps the `webpackIgnore` /
// `@vite-ignore` hints of its `import(url)` for the bundlers of our users
import loadRuntime from "./load-runtime.js";
import type {
  IArchive,
  IAssetsOptions,
  IFile,
  IInitializeOptions,
  IInstallOptions,
  ILogger,
  IPinnedPackage,
  IProgress,
  PyjsModule,
} from "./types";

export type Arch = "wasm32" | "wasm64";

const SILENT_LOGGER: ILogger = { log() {}, warn() {}, error() {} };

/** in a worker shared libraries need not be preloaded (sync compilation is allowed there) */
export function isWorker(): boolean {
  const g = globalThis as any;
  return typeof g.WorkerGlobalScope !== "undefined" && g.self instanceof g.WorkerGlobalScope;
}

function withTrailingSlash(url: string | URL): string {
  const s = url.toString();
  return s.endsWith("/") ? s : `${s}/`;
}

/** the page (or worker) URL: base of relative URLs */
function pageUrl(): string {
  return globalThis.location?.href ?? "http://localhost/";
}

/**
 * `assets/` next to this module, when served as published (CDN, static
 * hosting). Deliberately not `new URL("<literal>", import.meta.url)`:
 * bundlers would try to resolve (and fail on) the directory.
 */
function moduleAssetsUrl(): string | undefined {
  try {
    const here = import.meta.url;
    if (!here) {
      return undefined;
    }
    return new URL("../assets/", here.replace(/[^/]*$/, "")).href;
  } catch {
    return undefined;
  }
}

/** the env meta of `arch` below `root`, undefined if not there (404, an html fallback page, ...) */
async function tryEnvMeta(root: string, arch: Arch): Promise<any | undefined> {
  try {
    const response = await fetch(new URL(`${arch}/empack_env_meta.json`, root).href);
    if (!response.ok) {
      return undefined;
    }
    const meta = JSON.parse(await response.text());
    return Array.isArray(meta?.packages) ? meta : undefined;
  } catch {
    return undefined;
  }
}

const SELF_HOST_HINT =
  `self-host them with \`npx ${PACKAGE_NAME} copy-assets <dir>\` and pass ` +
  "`assetsUrl` (the url of <dir>)";
let warnedCdn = false;

/**
 * Where the runtime + python environment are served from:
 * 1. `assetsUrl` if given,
 * 2. `assets/` next to this module (unbundled: CDN, static hosting),
 * 3. (bundled apps) the CDN, for exactly this package version.
 */
async function resolveAssets(arch: Arch, options: IAssetsOptions): Promise<{ root: string; envMeta: any }> {
  if (options.assetsUrl !== undefined) {
    const root = withTrailingSlash(new URL(options.assetsUrl.toString(), pageUrl()).href);
    const envMeta = await tryEnvMeta(root, arch);
    if (!envMeta) {
      throw new Error(`pyjs: no ${arch} runtime at assetsUrl ${root} (${arch}/empack_env_meta.json not found); ${SELF_HOST_HINT}`);
    }
    return { root, envMeta };
  }
  const local = moduleAssetsUrl();
  if (local) {
    const envMeta = await tryEnvMeta(local, arch);
    if (envMeta) {
      return { root: local, envMeta };
    }
  }
  if (options.cdnFallback === false) {
    throw new Error(
      `pyjs: the runtime files are not next to the module (${local ?? "unknown location"}, e.g. in a bundled app); ${SELF_HOST_HINT}`
    );
  }
  const cdn = withTrailingSlash(options.cdnUrl ?? DEFAULT_CDN_URL);
  const envMeta = await tryEnvMeta(cdn, arch);
  if (!envMeta) {
    throw new Error(`pyjs: no ${arch} runtime at ${cdn}; ${SELF_HOST_HINT}`);
  }
  if (!warnedCdn) {
    warnedCdn = true;
    console.warn(
      `pyjs: runtime files not found next to the module (bundled app?), loading them from ${cdn}. ` +
        `To avoid that, ${SELF_HOST_HINT}.`
    );
  }
  return { root: cdn, envMeta };
}

/**
 * Compile the runtime wasm of `arch` (e.g. once in the main thread, then
 * posted to several workers: `initializePyjsRuntime({ wasmModule })`).
 */
export async function compileRuntime(arch: Arch, options: IAssetsOptions = {}): Promise<WebAssembly.Module> {
  const { root } = await resolveAssets(arch, options);
  const url = new URL(`${arch}/pyjs_runtime_browser.wasm`, root).href;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`pyjs: ${url}: HTTP ${response.status}`);
  }
  if ((response.headers.get("content-type") ?? "").includes("application/wasm")) {
    return WebAssembly.compileStreaming(response);
  }
  return WebAssembly.compile(await response.arrayBuffer());  // (servers without the wasm mime type)
}

/** the emscripten Module of the runtime (instantiated, no python yet) */
async function createRuntimeModule(assetsUrl: string, options: IInitializeOptions): Promise<any> {
  const { default: createModule } = await loadRuntime(new URL("pyjs_runtime_browser.mjs", assetsUrl).href);
  const moduleArg: Record<string, unknown> = {
    locateFile: (path: string) => new URL(path, assetsUrl).href,
    ...(options.print ? { print: options.print } : {}),
    ...(options.printErr ? { printErr: options.printErr } : {}),
    ...(options.moduleOptions ?? {}),
  };
  const wasmModule = options.wasmModule;
  if (wasmModule) {
    // emscripten's hook: instantiate the module compiled elsewhere
    moduleArg.instantiateWasm = (imports: WebAssembly.Imports, done: (i: WebAssembly.Instance, m: WebAssembly.Module) => void) => {
      WebAssembly.instantiate(wasmModule, imports).then((instance) => done(instance, wasmModule));
      return {};
    };
  }
  return createModule(moduleArg);
}

/** a promise whose rejection is handled later (no "unhandled rejection" meanwhile) */
function deferred<T>(promise: Promise<T>): Promise<T> {
  promise.catch(() => {});
  return promise;
}

interface IState {
  Module: any;
  arch: Arch;
  envMeta: any;
  pythonVersion: number[];
  channels: string[];
  logger: ILogger;
  cacheName?: string;
  /** python's .pyc files per package (undefined: off) */
  bytecode?: BytecodeCache;
  verify: boolean;
  preload: boolean;
  onProgress?: (p: IProgress) => void;
  /** packages installed besides the shipped environment */
  installed: Map<string, IInstalled>;
  /** files of the shipped environment's packages (name -> files) */
  envFiles: Map<string, string[]>;
  /** the URL of the shipped tarballs (`assets/<arch>/`) */
  assetsUrl: string;
  /** optional shipped packages not installed yet (name -> env meta entry), see `optionalPackages` */
  optional: Map<string, any>;
  /** specs of all solves so far */
  specs: string[];
  /** one install at a time (they change the same file system) */
  queue: Promise<unknown>;
  /** phase times (ms) of the initialization / the running install, see initialize */
  timings?: Record<string, number>;
}

/** add the time since `since` to a phase of the initialization (no-op later) */
function addTiming(state: IState, key: string, since: number): void {
  if (state.timings && !Object.isFrozen(state.timings)) {
    state.timings[key] = (state.timings[key] ?? 0) + performance.now() - since;
  }
}

/** a package to install: its final layout from the cache, or its file; its cached bytecode */
interface ILoadedPackage {
  extracted?: IExtractedPackage;
  bytes?: Uint8Array;
  bytecode?: Uint8Array;
}

/** the package from the extracted cache, else downloaded (sha256 checked when asked) */
async function loadPackage(state: IState, ref: IPackageRef, onProgress: ((p: IProgress) => void) | undefined, verify: boolean): Promise<ILoadedPackage> {
  const bytecode = state.bytecode?.read(ref.url);
  // (a sha256 to check: only the downloaded file can be checked, not the cached layout)
  const checked = verify && !!ref.sha256;
  const extracted = checked ? undefined : await readExtracted(state.cacheName, ref.url);
  if (extracted) {
    onProgress?.({ item: ref.name, phase: "cached", done: extracted.tar.length, total: extracted.tar.length });
    return { extracted, bytecode: await bytecode };
  }
  const bytes = await fetchBytes(ref.url, { item: ref.name, sha256: ref.sha256, verify, onProgress });
  return { bytes, bytecode: await bytecode };
}

function downloadPackages(state: IState, refs: IPackageRef[], onProgress?: (p: IProgress) => void, verify = state.verify) {
  return refs.map((ref) => ({ ref, bytes: deferred(loadPackage(state, ref, onProgress, verify)) }));
}

/** install downloaded packages in order (old files of replaced packages removed first) -> shared libraries */
async function installDownloaded(
  state: IState,
  downloads: { ref: IPackageRef; bytes: Promise<ILoadedPackage> }[],
  onProgress?: (p: IProgress) => void
): Promise<{ names: string[]; sharedLibs: string[] }> {
  const sharedLibs: string[] = [];
  const names: string[] = [];
  for (const { ref, bytes } of downloads) {
    let t = performance.now();
    const data = await bytes;
    addTiming(state, "waitDownloads", t);
    t = performance.now();
    const old = state.installed.get(ref.name);
    if (old) {
      removeFiles(state.Module, old.files);
    } else if (state.envFiles.has(ref.name)) {
      removeFiles(state.Module, state.envFiles.get(ref.name) as string[]);
      state.envFiles.delete(ref.name);
    }
    let result: { files: string[]; sharedLibs: string[] };
    if (data.extracted) {
      result = installExtracted(state.Module, data.extracted);
    } else {
      const installed = installCondaPackage(state.Module, data.bytes as Uint8Array, state.pythonVersion, !!state.cacheName);
      if (installed.extracted) {
        // (not awaited: the next visit uses it)
        const { tar, placeholders } = installed.extracted;
        storeExtracted(state.cacheName, ref.url, tar, placeholders);
      }
      result = installed;
    }
    state.installed.set(ref.name, {
      version: ref.version,
      build: ref.build,
      filename: ref.filename,
      files: result.files,
      lockEntry: ref.lockEntry ?? lockEntryOfPinned(ref),
    });
    state.bytecode?.add(ref.name, ref.url, result.files, data.bytecode);
    sharedLibs.push(...result.sharedLibs);
    names.push(ref.name);
    addTiming(state, "extractPackages", t);
    onProgress?.({ item: ref.name, phase: "extract", done: 1, total: 1 });
  }
  return { names, sharedLibs };
}

/** pinned packages (no solve) -> refs; python / pyjs refused */
function pinnedRefs(urls: (string | IPinnedPackage)[]): IPackageRef[] {
  const refs = urls.map((u) => parsePinned(u, pageUrl()));
  for (const ref of refs) {
    if (PROTECTED_PACKAGES.has(ref.name)) {
      throw new Error(`pyjs: ${ref.name} is part of the runtime and cannot be replaced (${ref.url})`);
    }
  }
  return refs;
}

/** solve `specs` against the current state -> refs to install */
function solve(state: IState, specs: string[], channels: string[], logger: ILogger, onProgress?: (p: IProgress) => void) {
  onProgress?.({ item: "packages", phase: "solve", done: 0, total: 1 });
  return solveSpecs({
    specs,
    envMeta: state.envMeta,
    arch: state.arch,
    installed: state.installed,
    previousSpecs: state.specs,
    channels,
    logger,
  }).then((refs) => {
    state.specs.push(...specs);
    onProgress?.({ item: "packages", phase: "solve", done: 1, total: 1 });
    return refs;
  });
}

/** an archive to unpack: from the archive cache (its unpacked files as tar) or downloaded */
interface ILoadedArchive {
  archive: IArchive;
  url: string;
  /** the cache key (`cache: true` only): the URL + the destination */
  key?: string;
  extracted?: Uint8Array;
  bytes?: Uint8Array;
  bytecode?: Uint8Array;
}

/**
 * an archive with `cache: true` is cached like a package (its unpacked files
 * and their bytecode, by URL + destination: the URL must change when the
 * content does); without, it is downloaded (sha256 checked when asked)
 */
async function loadArchive(state: IState, archive: IArchive): Promise<ILoadedArchive> {
  const url = new URL(archive.url.toString(), pageUrl()).href;
  const checked = state.verify && !!archive.sha256;
  if (!archive.cache || !state.cacheName || checked) {
    const bytes = await fetchBytes(url, { item: url, sha256: archive.sha256, verify: state.verify, onProgress: state.onProgress });
    return { archive, url, bytes };
  }
  const key = `${url}${url.includes("?") ? "&" : "?"}pyjs-archive-path=${encodeURIComponent(archive.path)}`;
  const bytecode = state.bytecode?.read(key);
  const cached = await readExtracted(state.cacheName, key);
  if (cached) {
    state.onProgress?.({ item: url, phase: "cached", done: cached.tar.length, total: cached.tar.length });
    return { archive, url, key, extracted: cached.tar, bytecode: await bytecode };
  }
  const bytes = await fetchBytes(url, { item: url, onProgress: state.onProgress });
  return { archive, url, key, bytes, bytecode: await bytecode };
}

/** archives: their downloads / cache reads (started at once) */
function downloadArchives(state: IState, archives: IArchive[]) {
  return archives.map((archive) => ({ archive, loaded: deferred(loadArchive(state, archive)) }));
}

/** unpack a loaded archive below its path (cached: stored in the background) -> its files and shared libraries */
function installArchive(state: IState, loaded: ILoadedArchive): { files: string[]; sharedLibs: string[] } {
  const { archive, key } = loaded;
  let result: { files: string[]; sharedLibs: string[]; tar?: Uint8Array };
  if (loaded.extracted) {
    result = extractArchive(state.Module, loaded.extracted, archive.path);
  } else {
    result = extractArchive(state.Module, loaded.bytes as Uint8Array, archive.path, !!key);
    if (key && result.tar) {
      storeExtracted(state.cacheName, key, result.tar, []); // (not awaited: the next visit uses it)
    }
  }
  if (key) {
    state.bytecode?.add(`archive:${key}`, key, result.files, loaded.bytecode);
  }
  state.onProgress?.({ item: loaded.url, phase: "extract", done: 1, total: 1 });
  return { files: result.files, sharedLibs: result.sharedLibs };
}
function downloadFiles(state: IState, files: IFile[]) {
  return files.map((f) => {
    if (f.data !== undefined) {
      return { file: f, data: Promise.resolve(f.data) };
    }
    if (f.url === undefined) {
      throw new Error(`pyjs: file ${f.path} has neither data nor url`);
    }
    const url = new URL(f.url.toString(), pageUrl()).href;
    return { file: f, data: deferred<Uint8Array | string>(fetchBytes(url, { item: url, onProgress: state.onProgress })) };
  });
}

/**
 * The optional packages of the shipped environment: the extension modules of
 * python's stdlib that are side modules (python-ssl, python-sqlite3, ...,
 * marked `optional` by build_utils/npm_env_meta.py). Their tarballs are
 * shipped, but only installed when asked for: option `stdlib` or
 * `installPackages(["sqlite3"])`. The solver sees them as installed, so it
 * never downloads them from a channel.
 *
 * `names`: "all", or names with or without the "python-" prefix ("sqlite3",
 * "python-sqlite3") -> the env meta entries (unknown names are an error)
 */
function optionalPackages(available: Map<string, any>, names: string[] | "all" | undefined): any[] {
  // (a python with these modules built in has no optional packages: nothing to do)
  if (names === undefined || available.size === 0) {
    return [];
  }
  if (names === "all") {
    return [...available.values()];
  }
  return names.map((name) => {
    const entry = available.get(name) ?? available.get(`python-${name}`);
    if (!entry) {
      const known = [...available.keys()].map((n) => n.replace(/^python-/, ""));
      throw new Error(`pyjs: no optional stdlib package "${name}" (available: ${known.join(", ") || "none"})`);
    }
    return entry;
  });
}

/** the package name of a spec ("sqlite3", "python-ssl >=3", "numpy=2" -> its leading name) */
function specName(spec: string): string {
  return spec.trim().match(/^[A-Za-z0-9_.-]+/)?.[0] ?? spec;
}

/** extract a downloaded tarball of the shipped environment (no longer optional) -> its shared libraries */
function installEnvTarball(state: IState, item: any, url: string, bytes: Uint8Array, bytecode: Uint8Array | undefined): string[] {
  const result = extractArchive(state.Module, bytes, "/");
  // (env packages replaced by installed ones: their unit is replaced by name)
  state.bytecode?.add(item.name ?? item.filename, url, result.files, bytecode);
  if (item.name) {
    state.envFiles.set(item.name, result.files);
    state.optional.delete(item.name);
  }
  return result.sharedLibs;
}

/** load shared libraries in the main thread (worker: dlopen at import does it) */
async function linkSharedLibs(state: IState, sharedLibs: string[], onProgress?: (p: IProgress) => void): Promise<void> {
  if (!state.preload || sharedLibs.length === 0) {
    return;
  }
  onProgress?.({ item: "shared libraries", phase: "link", done: 0, total: sharedLibs.length });
  await preloadSharedLibs(state.Module, sharedLibs);
  onProgress?.({ item: "shared libraries", phase: "link", done: sharedLibs.length, total: sharedLibs.length });
}

/**
 * Create and initialize a pyjs runtime.
 *
 * @param arch the architecture of the runtime
 */
export async function initialize(arch: Arch, options: IInitializeOptions = {}): Promise<PyjsModule> {
  const logger = options.logger ?? (options.verbose ? console : SILENT_LOGGER);
  const onProgress = options.onProgress;
  // where the time goes (ms), as Module.initTimings: waiting for downloads /
  // the runtime vs. the work (extract, link, start); see docs/npm.md
  const t0 = performance.now();
  const timings: Record<string, number> = {};
  const add = (key: string, since: number) => (timings[key] = (timings[key] ?? 0) + performance.now() - since);

  const { root, envMeta } = await resolveAssets(arch, options);
  add("assets", t0);
  const assetsUrl = new URL(`${arch}/`, root).href;
  const python = envMeta.packages.find((p: any) => p.name === "python");
  if (!python) {
    throw new Error("pyjs: no python in the packed environment");
  }

  // 1. everything at once: the runtime, the solve, all downloads
  const modulePromise = deferred(createRuntimeModule(assetsUrl, options));
  const pythonVersion = python.version.split(".").map((x: string) => parseInt(x, 10));
  const cacheName = cacheNameOf(options.cache);
  const state: IState = {
    Module: undefined,
    arch,
    envMeta,
    pythonVersion,
    channels: options.channels ?? DEFAULT_CHANNELS,
    logger,
    cacheName,
    bytecode:
      cacheName && options.bytecodeCache !== false && typeof caches !== "undefined"
        ? new BytecodeCache(bytecodeCacheName(cacheName), pythonVersion)
        : undefined,
    verify: options.verifySha256 ?? false,
    preload: options.preloadSharedLibs ?? !isWorker(),
    onProgress,
    installed: new Map(),
    envFiles: new Map(),
    assetsUrl,
    optional: new Map(envMeta.packages.filter((p: any) => p.optional).map((p: any) => [p.name, p])),
    specs: [],
    queue: Promise.resolve(),
  };

  // the shipped environment: pre-relocated tarballs next to the runtime (not
  // in the package cache: their names are not versioned); of the optional
  // packages only the ones in `stdlib`
  const requested = new Set(optionalPackages(state.optional, options.stdlib));
  const envItems = [...envMeta.packages.filter((p: any) => !p.optional || requested.has(p)), ...(envMeta.mounts ?? [])];
  const envUrls: string[] = envItems.map((p: any) => new URL(p.filename, assetsUrl).href);
  const envDownloads = envItems.map((p: any, i: number) =>
    deferred(fetchBytes(envUrls[i], { item: p.name ?? p.filename, onProgress }))
  );
  const envBytecode = envUrls.map((url) => deferred(state.bytecode?.read(url) ?? Promise.resolve(undefined)));
  const pinned = downloadPackages(state, pinnedRefs(options.urls ?? []), onProgress);
  const solvedDownloads = deferred(
    options.packages?.length
      ? solve(state, options.packages, state.channels, logger, onProgress).then((refs) => {
          // pinned packages win over solved ones of the same name
          const pinnedNames = new Set(pinned.map((d) => d.ref.name));
          return downloadPackages(state, refs.filter((r) => !pinnedNames.has(r.name)), onProgress);
        })
      : Promise.resolve([])
  );
  const archives = downloadArchives(state, options.archives ?? []);
  const files = downloadFiles(state, options.files ?? []);

  // 2. extract in a fixed order
  let t = performance.now();
  const Module = await modulePromise;
  add("waitRuntime", t);
  state.Module = Module;
  if (state.bytecode) {
    state.bytecode.Module = Module;
  }
  state.timings = timings;
  const sharedLibs: string[] = [];
  for (let i = 0; i < envItems.length; i++) {
    t = performance.now();
    const bytes = await envDownloads[i];
    const bytecode = await envBytecode[i];
    add("waitDownloads", t);
    t = performance.now();
    sharedLibs.push(...installEnvTarball(state, envItems[i], envUrls[i], bytes, bytecode));
    add("extractEnv", t);
  }
  t = performance.now();
  const packageDownloads = [...pinned, ...(await solvedDownloads)];
  add("waitSolve", t);
  const installed = await installDownloaded(state, packageDownloads, onProgress);
  sharedLibs.push(...installed.sharedLibs);
  for (const { loaded } of archives) {
    t = performance.now();
    const archive = await loaded;
    add("waitDownloads", t);
    t = performance.now();
    sharedLibs.push(...installArchive(state, archive).sharedLibs);
    add("extractArchives", t);
  }
  for (const { file, data } of files) {
    writeFile(Module, file.path, await data);
  }

  // dependencies of shared libraries are found via LD_LIBRARY_PATH (also python's dlopen)
  Module.setenv("LD_LIBRARY_PATH", "/lib:/usr/lib");

  // 3. python, then the shared libraries: loading an extension module runs
  // its static initializers, which may already use the python C API
  onProgress?.({ item: "python", phase: "start", done: 0, total: 1 });
  t = performance.now();
  Module.startPython({ env: options.env });
  add("start", t);
  onProgress?.({ item: "python", phase: "start", done: 1, total: 1 });
  t = performance.now();
  await linkSharedLibs(state, sharedLibs, onProgress);
  add("link", t);
  add("total", t0);
  // (later installs do not add to them)
  Object.defineProperty(Module, "initTimings", { value: finishTimings(timings), enumerable: true });

  Object.defineProperty(Module, "pyjsArch", { value: arch, enumerable: true });
  Object.defineProperty(Module, "pythonVersion", { value: state.pythonVersion, enumerable: true });
  attachInstallers(state);
  Module.saveBytecode = () => state.bytecode?.save() ?? Promise.resolve();
  state.bytecode?.watch();
  return Module as PyjsModule;
}

/** phase times rounded to ms and frozen (no more additions) */
function finishTimings(timings: Record<string, number>): Readonly<Record<string, number>> {
  for (const key of Object.keys(timings)) {
    timings[key] = Math.round(timings[key]);
  }
  return Object.freeze(timings);
}

/** run `task` after the installs before it (one at a time) */
function enqueue<T>(state: IState, task: () => Promise<T>): Promise<T> {
  const result = state.queue.then(task);
  state.queue = result.catch(() => {});
  return result;
}

/** Module.installPackages / unpackArchive / addFiles (after python started) */
function attachInstallers(state: IState): void {
  const Module = state.Module;
  const invalidateCaches = () => Module.runPython("import importlib\nimportlib.invalidate_caches()");

  Module.installPackages = (packages: (string | IPinnedPackage)[], options: IInstallOptions = {}) =>
    enqueue(state, async () => {
      const logger = options.logger ?? (options.verbose ? console : state.logger);
      const onProgress = options.onProgress ?? state.onProgress;
      const allSpecs = packages.filter((p): p is string => typeof p === "string" && !/^[a-z]+:\/\//i.test(p) && !/\.(conda|tar\.bz2)$/.test(p));
      const pins = packages.filter((p) => !allSpecs.includes(p as string));
      // optional stdlib packages ("sqlite3", "python-ssl"): from the shipped
      // tarballs, not solved (the solver sees them as installed); already
      // installed ones are skipped
      const optionalNames = new Set(state.envMeta.packages.filter((p: any) => p.optional).map((p: any) => p.name));
      const shippedName = (spec: string) =>
        [specName(spec), `python-${specName(spec)}`].find((n) => optionalNames.has(n));
      const shipped = allSpecs
        .map(shippedName)
        .filter((n): n is string => n !== undefined && state.optional.has(n))
        .map((n) => state.optional.get(n));
      const specs = allSpecs.filter((s) => shippedName(s) === undefined);
      // phase times of this install -> Module.installTimings (as initTimings)
      const timings: Record<string, number> = {};
      state.timings = timings;
      const t0 = performance.now();
      const shippedLibs: string[] = [];
      for (const item of shipped) {
        const url = new URL(item.filename, state.assetsUrl).href;
        const bytes = await fetchBytes(url, { item: item.name, onProgress });
        shippedLibs.push(...installEnvTarball(state, item, url, bytes, await state.bytecode?.read(url)));
      }
      const refs = [
        ...pinnedRefs(pins),
        ...(specs.length ? await solve(state, specs, options.channels ?? state.channels, logger, onProgress) : []),
      ];
      addTiming(state, "solve", t0);
      const downloads = downloadPackages(state, refs, onProgress, options.verifySha256 ?? state.verify);
      const installed = await installDownloaded(state, downloads, onProgress);
      let t = performance.now();
      await linkSharedLibs(state, [...shippedLibs, ...installed.sharedLibs], onProgress);
      addTiming(state, "link", t);
      t = performance.now();
      invalidateCaches();
      addTiming(state, "invalidateCaches", t);
      addTiming(state, "total", t0);
      Module.installTimings = finishTimings(timings);
      return [...shipped.map((item) => item.name), ...installed.names];
    });

  Module.unpackArchive = (archive: IArchive) =>
    enqueue(state, async () => {
      const result = installArchive(state, await loadArchive(state, archive));
      await linkSharedLibs(state, result.sharedLibs, state.onProgress);
      invalidateCaches();
      return result.files;
    });

  Module.addFiles = (fileList: IFile[]) =>
    enqueue(state, async () => {
      for (const { file, data } of downloadFiles(state, fileList)) {
        writeFile(Module, file.path, await data);
      }
      invalidateCaches();
    });
}
