/**
 * `npx <package> lock <specs...>` (node): solve package specs at build time
 * against the python environment shipped in this package, write the result as
 * pinned packages: `{ "wasm32": [{url, sha256}], "wasm64": [...] }`. An app
 * then installs them without a solver in the browser:
 * `initializePyjsRuntime({ urls: lock.wasm32 })`.
 */
import fs from "node:fs";
import path from "node:path";

import { DEFAULT_CHANNELS } from "./constants";
import { solveSpecs } from "./solve";
import type { ILogger, IPinnedPackage } from "./types";

export interface ILockOptions {
  specs: string[];
  /** the package's assets/ dir (wasm32/, wasm64/ with empack_env_meta.json) */
  assetsDir: string;
  archs?: ("wasm32" | "wasm64")[];
  channels?: string[];
  logger?: ILogger;
}

/** the pinned packages per architecture */
export async function createLock(options: ILockOptions): Promise<Record<string, IPinnedPackage[]>> {
  const archs = options.archs ?? (["wasm32", "wasm64"] as const).filter((a) =>
    fs.existsSync(path.join(options.assetsDir, a, "empack_env_meta.json"))
  );
  const logger = options.logger ?? { log() {}, warn: console.warn, error: console.error };
  const lock: Record<string, IPinnedPackage[]> = {};
  for (const arch of archs) {
    const envMeta = JSON.parse(fs.readFileSync(path.join(options.assetsDir, arch, "empack_env_meta.json"), "utf8"));
    const refs = await solveSpecs({
      specs: options.specs,
      envMeta,
      arch,
      installed: new Map(),
      previousSpecs: [],
      channels: options.channels ?? DEFAULT_CHANNELS,
      logger,
    });
    lock[arch] = refs.map((r) => (r.sha256 ? { url: r.url, sha256: r.sha256 } : { url: r.url }));
  }
  return lock;
}
