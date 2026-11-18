/**
 * Solving package specs with mambajs (rattler). Loaded lazily (a few MB, in its
 * own chunk): only `packages` / `installPackages(specs)` need it, pinned
 * installs never load it.
 */
import type { IInstalled, IPackageRef } from "./install";
import type { ILogger } from "./types";

/** the solver module (mambajs + rattler), loaded on first use */
let solverPromise: Promise<typeof import("@emscripten-forge/mambajs")> | undefined;
export function loadSolver() {
  solverPromise ??= import("@emscripten-forge/mambajs");
  return solverPromise;
}

/** packages shipped with the runtime which must never be replaced */
export const PROTECTED_PACKAGES = new Set(["python", "pyjs"]);

export interface ISolveRequest {
  specs: string[];
  /** empack_env_meta.json of the shipped environment */
  envMeta: any;
  arch: "wasm32" | "wasm64";
  /** what is installed besides the shipped environment (name -> record) */
  installed: Map<string, IInstalled>;
  /** specs of earlier solves (they stay requirements) */
  previousSpecs: string[];
  channels: string[];
  logger: ILogger;
}

/** the channel URL of a package URL (`<channel>/<subdir>/<file>`) */
function channelOf(url: string): { channel: string; subdir: string } {
  const parts = url.split("/");
  const subdir = parts[parts.length - 2];
  return { channel: parts.slice(0, -2).join("/"), subdir };
}

/**
 * the packages (to add or replace) that `specs` need on top of what is
 * installed; python / pyjs are never replaced (a solve that wants another
 * python is an error)
 */
export async function solveSpecs(req: ISolveRequest): Promise<IPackageRef[]> {
  const m = await loadSolver();
  const base = m.empackLockToMambajsLock({ empackEnvMeta: req.envMeta, pkgRootUrl: "" });
  base.platform = `emscripten-${req.arch}` as typeof base.platform;
  base.specs = [...(base.specs ?? []), ...req.previousSpecs];

  // what was installed after the shipped env (solved: their lock entry; pinned:
  // an entry for their channel)
  for (const [name, rec] of req.installed) {
    for (const key of Object.keys(base.packages)) {
      if (base.packages[key].name === name) {
        delete base.packages[key];
      }
    }
    if (rec.lockEntry) {
      base.packages[rec.filename] = rec.lockEntry as any;
    }
  }

  // channel order = priority: the requested channels first (mambajs would append
  // new channels after the env's, so a self-hosted channel could not override a
  // published package)
  const requested = m.formatChannels(req.channels, req.logger);
  base.channels = [...requested.channels, ...base.channels.filter((c) => !requested.channels.includes(c))];
  base.channelInfo = { ...base.channelInfo, ...requested.channelInfo };
  for (const rec of req.installed.values()) {
    const channel = (rec.lockEntry as any)?.channel;
    if (channel && !base.channelInfo[channel]) {
      base.channelInfo[channel] = [{ url: channel, protocol: "https" }];
    }
  }

  const solved = await m.install(req.specs, base, [], req.logger);

  const current = new Map<string, { version: string; build?: string }>();
  for (const pkg of Object.values(base.packages)) {
    current.set(pkg.name, pkg);
  }
  const result: IPackageRef[] = [];
  for (const [filename, pkg] of Object.entries(solved.packages)) {
    const have = current.get(pkg.name);
    if (have && have.version === pkg.version && have.build === pkg.build) {
      continue;
    }
    if (PROTECTED_PACKAGES.has(pkg.name)) {
      if (pkg.name === "python") {
        throw new Error(`pyjs: the requested packages need python ${pkg.version} (${pkg.build}), this runtime ships another one`);
      }
      req.logger.log(`skipping ${pkg.name} ${pkg.version} (part of the runtime)`);
      continue;
    }
    result.push({
      url: m.computePackageUrl(pkg, filename, solved.channelInfo),
      filename,
      name: pkg.name,
      version: pkg.version,
      build: pkg.build ?? "",
      sha256: pkg.hash?.sha256,
      lockEntry: { ...pkg },
    });
  }
  return result;
}

/** a lock entry for a pinned package (so later solves know it is installed) */
export function lockEntryOfPinned(ref: IPackageRef): Record<string, unknown> {
  const { channel, subdir } = channelOf(ref.url);
  return { name: ref.name, version: ref.version, build: ref.build, subdir, channel };
}
