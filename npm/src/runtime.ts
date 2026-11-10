/**
 * Initialization of the pyjs runtime, shared by the wasm32 and the wasm64 entry.
 *
 * Same path as jupyterlite-xeus: the packed environment (python + stdlib + the
 * pyjs python module, built with empack) is extracted with untarjs into the
 * emscripten FS *before* the interpreter starts, then the existing pyjs
 * initialization (`Module.init_phase_1` / `init_phase_2`, pre_js/init.js) runs.
 * Extra conda packages are solved with mambajs (rattler, loaded lazily).
 */
import {
  bootstrapEmpackPackedEnvironment,
  bootstrapPython,
  computeCondaPackagesDiff,
  empackLockToMambajsLock,
  getPythonVersion,
  installPackagesToEmscriptenFS,
  loadSharedLibs,
  removePackagesFromEmscriptenFS,
  type IEmpackEnvMeta,
  type ILock,
  type ISolvedPackages,
  type TSharedLibsMap,
} from "@emscripten-forge/mambajs-core";
import { initUntarJS, type IUnpackJSAPI } from "@emscripten-forge/untarjs";

import { DEFAULT_CHANNELS, PACKAGE_NAME, DEFAULT_CDN_URL } from "./constants";
// a plain (unminified, not bundled by us) module: keeps the `webpackIgnore` /
// `@vite-ignore` hints of its `import(url)` for the bundlers of our users
import loadRuntime from "./load-runtime.js";
import type { IInitializeOptions, IInstallOptions, ILogger, PyjsModule } from "./types";

export type Arch = "wasm32" | "wasm64";


/** packages shipped with this npm package which must not be replaced at runtime */
const PROTECTED_PACKAGES = new Set(["python", "pyjs"]);

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
async function tryEnvMeta(root: string, arch: Arch): Promise<IEmpackEnvMeta | undefined> {
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
async function resolveAssets(
  arch: Arch,
  options: IInitializeOptions
): Promise<{ root: string; envMeta: IEmpackEnvMeta }> {
  if (options.assetsUrl !== undefined) {
    const root = withTrailingSlash(new URL(options.assetsUrl.toString(), globalThis.location?.href).href);
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

/** the solver (mambajs + rattler, a few MB) is only loaded when packages are installed */
let solverPromise: Promise<typeof import("@emscripten-forge/mambajs")> | undefined;
function loadSolver() {
  solverPromise ??= import("@emscripten-forge/mambajs");
  return solverPromise;
}

async function solve(
  specs: string[],
  lock: ILock,
  channels: string[],
  logger: ILogger
): Promise<ILock> {
  const { install } = await loadSolver();
  // `install` extends the channels of the lock it gets
  return install(specs, structuredClone(lock), channels, logger);
}

interface IState {
  Module: any;
  arch: Arch;
  lock: ILock;
  paths: { [key: string]: any };
  untarjs: IUnpackJSAPI;
  prefix: string;
  pythonVersion: number[];
  channels: string[];
  logger: ILogger;
  preloadSharedLibs: boolean;
  pythonRunning: boolean;
  queue: Promise<unknown>;
}

/**
 * Install the packages of `newLock` which are not in `state.lock` (and remove
 * the ones replaced by them). Returns the shared libs of the new packages.
 */
async function applyLock(state: IState, newLock: ILock): Promise<{ installed: string[]; sharedLibs: TSharedLibsMap }> {
  const diff = computeCondaPackagesDiff({ oldLock: state.lock, newLock });

  const newPackages: ISolvedPackages = {};
  for (const [filename, pkg] of Object.entries(diff.newPackages)) {
    if (PROTECTED_PACKAGES.has(pkg.name)) {
      if (pkg.name === "python") {
        throw new Error(
          `pyjs: the requested packages need python ${pkg.version} (${pkg.build}), ` +
            `this runtime ships python ${state.pythonVersion.join(".")}`
        );
      }
      // e.g. a package depending on the conda package `pyjs`: the pyjs
      // shipped with the runtime is used
      state.logger.log(`skipping ${pkg.name} ${pkg.version} (part of the runtime)`);
      continue;
    }
    newPackages[filename] = pkg;
  }
  const removed: ISolvedPackages = {};
  for (const [filename, pkg] of Object.entries(diff.removedPackages)) {
    if (!PROTECTED_PACKAGES.has(pkg.name)) {
      removed[filename] = pkg;
    }
  }

  if (Object.keys(removed).length > 0) {
    state.paths = await removePackagesFromEmscriptenFS({
      removedPackages: { packages: removed, pipPackages: {} },
      Module: state.Module,
      paths: state.paths,
      logger: state.logger,
    });
  }
  const installed = await installPackagesToEmscriptenFS({
    packages: { packages: newPackages, pipPackages: {} },
    channels: newLock.channelInfo,
    Module: state.Module,
    pythonVersion: state.pythonVersion,
    untarjs: state.untarjs,
    logger: state.logger,
  });
  state.paths = { ...state.paths, ...installed.paths };
  state.lock = newLock;
  return {
    installed: Object.values(newPackages).map((pkg) => pkg.name),
    sharedLibs: installed.sharedLibs,
  };
}

async function preloadSharedLibs(state: IState, sharedLibs: TSharedLibsMap): Promise<void> {
  if (state.preloadSharedLibs && Object.keys(sharedLibs).length > 0) {
    await loadSharedLibs({ sharedLibs, prefix: state.prefix, Module: state.Module, logger: state.logger });
  }
}

async function installPackages(state: IState, specs: string[], options: IInstallOptions = {}): Promise<string[]> {
  const logger = options.logger ?? (options.verbose ? console : state.logger);
  const newLock = await solve(specs, state.lock, options.channels ?? state.channels, logger);
  const { installed, sharedLibs } = await applyLock(state, newLock);
  await preloadSharedLibs(state, sharedLibs);
  if (state.pythonRunning) {
    state.Module.exec("import importlib\nimportlib.invalidate_caches()");
  }
  return installed;
}

/**
 * Create and initialize a pyjs runtime.
 *
 * @param arch the architecture of the runtime
 */
export async function initialize(arch: Arch, options: IInitializeOptions = {}): Promise<PyjsModule> {
  const verbose = options.verbose ?? false;
  const logger = options.logger ?? (verbose ? console : SILENT_LOGGER);
  const channels = options.channels ?? DEFAULT_CHANNELS;
  const extraPackages = options.extraPackages ?? options.extra_packages ?? [];

  if (extraPackages.length > 0) {
    // already start loading the solver
    loadSolver().catch(() => {});
  }
  const { root, envMeta: empackEnvMeta } = await resolveAssets(arch, options);
  // directory of the runtime + packed environment of this architecture
  const assetsUrl = new URL(`${arch}/`, root).href;
  const untarjsPromise = initUntarJS(() => new URL("untarjs.wasm", root).href);

  const { default: createModule } = await loadRuntime(new URL("pyjs_runtime_browser.mjs", assetsUrl).href);
  const Module = await createModule({
    locateFile: (path: string) => new URL(path, assetsUrl).href,
    ...(options.print ? { print: options.print } : {}),
    ...(options.printErr ? { printErr: options.printErr } : {}),
    ...(options.moduleOptions ?? {}),
  });

  const untarjs = await untarjsPromise;
  const lock = empackLockToMambajsLock({ empackEnvMeta, pkgRootUrl: assetsUrl.replace(/\/$/, "") });
  lock.platform = `emscripten-${arch}` as ILock["platform"];

  const solved = extraPackages.length > 0 ? solve(extraPackages, lock, channels, logger) : undefined;
  // keep the solver error for later, the bootstrap continues meanwhile
  solved?.catch(() => {});

  logger.log(`pyjs (${arch}): extracting the environment`);
  const bootstrapped = await bootstrapEmpackPackedEnvironment({
    empackEnvMeta,
    lock,
    pkgRootUrl: assetsUrl.replace(/\/$/, ""),
    Module,
    untarjs,
    logger,
  });
  const pythonVersion = bootstrapped.pythonVersion ?? getPythonVersion(lock);
  if (!pythonVersion) {
    throw new Error("pyjs: no python in the packed environment");
  }

  const state: IState = {
    Module,
    arch,
    lock,
    paths: bootstrapped.paths,
    untarjs,
    prefix: empackEnvMeta.prefix,
    pythonVersion,
    channels,
    logger,
    preloadSharedLibs: options.preloadSharedLibs ?? !isWorker(),
    pythonRunning: false,
    queue: Promise.resolve(),
  };

  let sharedLibs: TSharedLibsMap = bootstrapped.sharedLibs;
  if (solved) {
    logger.log(`pyjs (${arch}): installing ${extraPackages.join(", ")}`);
    const extra = await applyLock(state, await solved);
    sharedLibs = { ...sharedLibs, ...extra.sharedLibs };
  }

  // emscripten (>= 4) ignores the `fs` option mambajs-core passes to
  // `loadDynamicLibrary`: dependencies of shared libs (e.g. numpy ->
  // libopenblas.so) are found via LD_LIBRARY_PATH, otherwise they are fetched
  // by URL. Also used by python's dlopen.
  const libDir = `${state.prefix.replace(/\/$/, "")}/lib`;
  Module.setenv("LD_LIBRARY_PATH", libDir === "/lib" ? "/lib:/usr/lib" : `${libDir}:/lib:/usr/lib`);

  logger.log(`pyjs (${arch}): starting python ${pythonVersion.join(".")}`);
  await bootstrapPython({ prefix: state.prefix, pythonVersion, Module, verbose });
  state.pythonRunning = true;
  await preloadSharedLibs(state, sharedLibs);

  Object.defineProperty(Module, "pyjsArch", { value: arch, enumerable: true });
  Object.defineProperty(Module, "pythonVersion", { value: pythonVersion, enumerable: true });
  // one install at a time (they change the same file system / lock)
  Module.installPackages = (specs: string[], installOptions?: IInstallOptions) => {
    const result = state.queue.then(() => installPackages(state, specs, installOptions));
    state.queue = result.catch(() => {});
    return result;
  };
  return Module as PyjsModule;
}
