/**
 * Installing conda packages and archives into the emscripten file system with
 * the runtime's extractor (`Module._extract_archive`, libarchive, see
 * src/extract.cpp): conda layout, prefix relocation, per package file lists
 * (so a replaced package's files are removed).
 */
import type { IPinnedPackage } from "./types";

/** a conda package to install: where it is + what it is */
export interface IPackageRef {
  url: string;
  name: string;
  version: string;
  build: string;
  filename: string;
  sha256?: string;
  /** the solver's lock entry (packages from a solve), for later solves */
  lockEntry?: Record<string, unknown>;
}

/** an installed package (or a tarball of the shipped environment) */
export interface IInstalled {
  version: string;
  build: string;
  filename: string;
  files: string[];
  lockEntry?: Record<string, unknown>;
}

/** "name-version-build.conda" / ".tar.bz2" -> its parts */
export function parseCondaFilename(filename: string): { name: string; version: string; build: string } {
  const stem = filename.replace(/\.(conda|tar\.bz2)$/, "");
  if (stem === filename) {
    throw new Error(`pyjs: not a conda package file name (.conda / .tar.bz2): ${filename}`);
  }
  const parts = stem.split("-");
  if (parts.length < 3) {
    throw new Error(`pyjs: not a conda package file name (name-version-build): ${filename}`);
  }
  const build = parts.pop() as string;
  const version = parts.pop() as string;
  return { name: parts.join("-"), version, build };
}

/** a pinned package (URL string or `{url, sha256}`) -> its reference */
export function parsePinned(pinned: string | IPinnedPackage, base: string): IPackageRef {
  const p = typeof pinned === "string" ? { url: pinned } : pinned;
  const url = new URL(p.url, base).href;
  const filename = decodeURIComponent(new URL(url).pathname.split("/").pop() ?? "");
  return { url, filename, sha256: p.sha256, ...parseCondaFilename(filename) };
}

/** what `_extract_archive` returns */
interface IExtracted {
  files: string[];
  sharedLibs: string[];
  meta: Record<string, Uint8Array>;
  tar?: Uint8Array;
}

/** a text file whose prefix placeholder is replaced by the prefix "/" */
export interface IPlaceholder {
  path: string;
  placeholder: string;
}

/** the text files with a placeholder of `info/paths.json` (binary ones are left as they are) */
function placeholdersOf(pathsJson: Uint8Array | undefined): IPlaceholder[] {
  if (!pathsJson) {
    return [];
  }
  const paths = JSON.parse(new TextDecoder().decode(pathsJson)).paths ?? [];
  return paths
    .filter((e: any) => e.prefix_placeholder && e.file_mode !== "binary")
    .map((e: any) => ({ path: `/${e._path}`, placeholder: e.prefix_placeholder }));
}

/**
 * replace the placeholders: the prefix is "/", "<placeholder>/lib/x" -> "/lib/x"
 * (the modification time stays: python's bytecode caches are validated against it)
 */
function relocate(Module: any, placeholders: IPlaceholder[]): void {
  for (const { path, placeholder } of placeholders) {
    if (!Module.FS.analyzePath(path).exists) {
      continue;
    }
    const mtime = Module.FS.stat(path).mtime.getTime();
    const text: string = Module.FS.readFile(path, { encoding: "utf8" });
    Module.FS.writeFile(path, text.split(placeholder).join(""));
    Module.FS.utime(path, mtime, mtime);
  }
}

/** python's bytecode cache files of the .py files among `files` (whether they exist or not) */
export function bytecodeFiles(files: string[], pythonVersion: number[]): string[] {
  const suffix = `.cpython-${pythonVersion[0]}${pythonVersion[1]}.pyc`;
  return files
    .filter((f) => f.endsWith(".py"))
    .map((f) => {
      const slash = f.lastIndexOf("/");
      return `${f.slice(0, slash)}/__pycache__/${f.slice(slash + 1, -3)}${suffix}`;
    });
}

/** an installed package as the extracted cache keeps it: its final layout (uncompressed tar) */
export interface IExtractedPackage {
  tar: Uint8Array;
  placeholders: IPlaceholder[];
}

/**
 * extract a conda package into "/" -> its files and shared libraries; with
 * `keep`, also its final layout for the extracted cache
 */
export function installCondaPackage(
  Module: any,
  bytes: Uint8Array,
  pythonVersion: number[],
  keep = false
): { files: string[]; sharedLibs: string[]; extracted?: IExtractedPackage } {
  const sitePackages = `lib/python${pythonVersion[0]}.${pythonVersion[1]}/site-packages/`;
  const result: IExtracted = Module._extract_archive(bytes, "/", {
    conda: true,
    meta: ["info/paths.json"],
    // noarch python packages: site-packages/ -> lib/pythonX.Y/site-packages/
    rename: [["site-packages/", sitePackages]],
    tar: keep,
  });
  const placeholders = placeholdersOf(result.meta["info/paths.json"]);
  relocate(Module, placeholders);
  return {
    files: result.files,
    sharedLibs: result.sharedLibs,
    extracted: keep && result.tar ? { tar: result.tar, placeholders } : undefined,
  };
}

/** install a package from the extracted cache: untar (no decompression), relocate */
export function installExtracted(Module: any, extracted: IExtractedPackage): { files: string[]; sharedLibs: string[] } {
  const result: IExtracted = Module._extract_archive(extracted.tar, "/", {});
  relocate(Module, extracted.placeholders);
  return { files: result.files, sharedLibs: result.sharedLibs };
}

/**
 * extract any archive below `dest` -> its files and shared libraries; with
 * `keep`, also what was written as an uncompressed tar (paths relative to
 * `dest`) for the archive cache
 */
export function extractArchive(
  Module: any,
  bytes: Uint8Array,
  dest: string,
  keep = false
): { files: string[]; sharedLibs: string[]; tar?: Uint8Array } {
  const result: IExtracted = Module._extract_archive(bytes, dest, { tar: keep });
  return { files: result.files, sharedLibs: result.sharedLibs, tar: keep ? result.tar : undefined };
}

/** remove the files of a package (replaced / removed) */
export function removeFiles(Module: any, files: string[]): void {
  for (const path of files) {
    try {
      Module.FS.unlink(path);
    } catch {
      // already gone (e.g. overwritten by another package and removed with it)
    }
  }
}

/** write a file, creating its directory */
export function writeFile(Module: any, path: string, data: Uint8Array | string): void {
  const dir = path.slice(0, path.lastIndexOf("/"));
  if (dir) {
    Module.FS.mkdirTree(dir);
  }
  Module.FS.writeFile(path, data);
}
