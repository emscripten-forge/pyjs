/**
 * The bytecode cache: python's `__pycache__/*.pyc` files of each installed
 * package (and of the shipped environment), kept in Cache Storage by package
 * URL and restored with the package on the next visit, so imports load
 * bytecode instead of compiling the sources again.
 *
 * Python writes the files at import time; they are saved when there are new
 * ones (checked every few seconds, and when the page is hidden) or on
 * `Module.saveBytecode()`. Python validates every cache file against the
 * modification time + size of its source, which the extraction keeps from the
 * archive: a stale or foreign file is recompiled, never used.
 */
import { bytecodeFiles } from "./install";

const CHECK_INTERVAL_MS = 3000;

/** a unit of the bytecode cache: one package (or env tarball) */
interface IUnit {
  url: string;
  /** the possible .pyc files of its .py files */
  pyc: string[];
  /** its __pycache__ directories */
  dirs: string[];
  /** the number of entries in `dirs` at the last save / restore */
  saved: number;
}

export class BytecodeCache {
  private units = new Map<string, IUnit>();
  private saving: Promise<void> = Promise.resolve();
  /** the runtime (set once it exists; reading the cache needs none) */
  Module: any;

  constructor(private cacheName: string, private pythonVersion: number[]) {}

  /** the cached bytecode of the package at `url` (undefined if none) */
  async read(url: string): Promise<Uint8Array | undefined> {
    try {
      const hit = await (await caches.open(this.cacheName)).match(url);
      return hit ? new Uint8Array(await hit.arrayBuffer()) : undefined;
    } catch {
      return undefined;
    }
  }

  /** a package was installed (`name` replaces an earlier one), with its cached bytecode */
  add(name: string, url: string, files: string[], bytecode?: Uint8Array): void {
    const pyc = bytecodeFiles(files, this.pythonVersion);
    const dirs = [...new Set(pyc.map((p) => p.slice(0, p.lastIndexOf("/"))))];
    const unit = { url, pyc, dirs, saved: 0 };
    if (bytecode) {
      try {
        this.Module._extract_archive(bytecode, "/", {});
        unit.saved = this.count(unit);
      } catch {
        // (a broken entry: compiled again)
      }
    }
    // (without a restored entry .pyc files already there, e.g. of a replaced
    // version, count as new: the next save stores them)
    this.units.set(name, unit);
  }

  /** a package was removed */
  remove(name: string): void {
    this.units.delete(name);
  }

  /** the number of files in the unit's __pycache__ directories */
  private count(unit: IUnit): number {
    let n = 0;
    for (const dir of unit.dirs) {
      try {
        n += this.Module.FS.readdir(dir).length;
      } catch {
        // (no __pycache__ yet)
      }
    }
    return n;
  }

  /** save the bytecode of the units with new files (one save at a time) */
  save(): Promise<void> {
    this.saving = this.saving.then(async () => {
      const changed = [...this.units.values()].filter((u) => this.count(u) !== u.saved);
      if (changed.length === 0) {
        return;
      }
      const cache = await caches.open(this.cacheName);
      for (const unit of changed) {
        unit.saved = this.count(unit);
        const tar: Uint8Array = this.Module._tar_files(unit.pyc);
        await cache.put(unit.url, new Response(tar as BodyInit, { headers: { "content-type": "application/x-tar" } }));
      }
    }).catch(() => {}); // (the next visit compiles again)
    return this.saving;
  }

  /** save automatically: every few seconds when there is something new, and when the page is hidden */
  watch(): void {
    const timer: any = setInterval(() => this.save(), CHECK_INTERVAL_MS);
    timer?.unref?.(); // (node: does not keep the process alive)
    const doc = (globalThis as any).document;
    doc?.addEventListener?.("visibilitychange", () => {
      if (doc.visibilityState === "hidden") {
        this.save();
      }
    });
  }
}

/** the bytecode cache's name for a package cache name */
export function bytecodeCacheName(cacheName: string): string {
  return `${cacheName}-bytecode`;
}
