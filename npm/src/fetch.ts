/**
 * Downloads: progress (bytes), sha256 checks (only when asked), a limit on
 * parallel downloads; the package cache (Cache Storage: installed packages'
 * final layouts, see readExtracted / storeExtracted).
 */
import type { IProgress } from "./types";

// conda packages as installed: their final layout as an uncompressed tar (a
// warm install only untars: no bzip2 / zstd, no conda handling), by package URL
export const DEFAULT_CACHE = "pyjs-packages-v2";
const PLACEHOLDERS_HEADER = "x-pyjs-placeholders";
const MAX_PARALLEL_DOWNLOADS = 6;

export interface IFetchOptions {
  /** name for the progress events */
  item: string;
  /** checked when given and `verify` is set */
  sha256?: string;
  verify?: boolean;
  onProgress?: (p: IProgress) => void;
}

/** at most `limit` running at once (downloads: memory, connections) */
function createLimiter(limit: number) {
  let running = 0;
  const waiting: (() => void)[] = [];
  return async function run<T>(task: () => Promise<T>): Promise<T> {
    if (running >= limit) {
      await new Promise<void>((resolve) => waiting.push(resolve));
    }
    running++;
    try {
      return await task();
    } finally {
      running--;
      waiting.shift()?.();
    }
  };
}
const limit = createLimiter(MAX_PARALLEL_DOWNLOADS);

/** the Cache Storage cache, undefined where there is none (opaque origins, ...) */
async function openCache(name: string | undefined): Promise<Cache | undefined> {
  if (!name || typeof caches === "undefined") {
    return undefined;
  }
  try {
    return await caches.open(name);
  } catch {
    return undefined;
  }
}

/** hex sha256 of `bytes` */
async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes as BufferSource);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

async function checkSha256(bytes: Uint8Array, url: string, options: IFetchOptions): Promise<void> {
  if (!options.verify || !options.sha256) {
    return;
  }
  const actual = await sha256Hex(bytes);
  if (actual !== options.sha256.toLowerCase()) {
    throw new Error(`pyjs: sha256 mismatch for ${url}: expected ${options.sha256}, got ${actual}`);
  }
}

/** the body of `response`, reporting bytes as they arrive */
async function readBody(response: Response, options: IFetchOptions): Promise<Uint8Array> {
  const total = Number(response.headers.get("content-length")) || 0;
  const report = (done: number) => options.onProgress?.({ item: options.item, phase: "download", done, total });
  if (!response.body) {
    const bytes = new Uint8Array(await response.arrayBuffer());
    report(bytes.length);
    return bytes;
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let received = 0;
  report(0);
  for (;;) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    chunks.push(value);
    received += value.length;
    report(received);
  }
  if (chunks.length === 1) {
    return chunks[0];
  }
  const bytes = new Uint8Array(received);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  return bytes;
}

/** the bytes at `url` (sha256 checked only with `verify`) */
export function fetchBytes(url: string, options: IFetchOptions): Promise<Uint8Array> {
  return limit(async () => {
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`pyjs: ${url}: HTTP ${response.status}`);
    }
    const bytes = await readBody(response, options);
    await checkSha256(bytes, url, options);
    return bytes;
  });
}

/** a package's final layout from the cache, undefined if not there */
export async function readExtracted(
  cacheName: string | undefined,
  url: string
): Promise<{ tar: Uint8Array; placeholders: { path: string; placeholder: string }[] } | undefined> {
  const cache = await openCache(cacheName);
  const hit = await cache?.match(url).catch(() => undefined);
  if (!hit) {
    return undefined;
  }
  try {
    const placeholders = JSON.parse(decodeURIComponent(hit.headers.get(PLACEHOLDERS_HEADER) ?? "%5B%5D"));
    return { tar: new Uint8Array(await hit.arrayBuffer()), placeholders };
  } catch {
    return undefined; // (a broken entry: installed from the package again)
  }
}

/** keep a package's final layout (failures are ignored: the next visit extracts again) */
export async function storeExtracted(
  cacheName: string | undefined,
  url: string,
  tar: Uint8Array,
  placeholders: { path: string; placeholder: string }[]
): Promise<void> {
  const header = encodeURIComponent(JSON.stringify(placeholders));
  if (header.length > 32768) {
    return; // (headers are not made for that much)
  }
  const cache = await openCache(cacheName);
  const headers = { "content-type": "application/x-tar", [PLACEHOLDERS_HEADER]: header };
  await cache?.put(url, new Response(tar as BodyInit, { headers })).catch(() => {});
}

/** the cache name of the `cache` option */
export function cacheNameOf(cache: boolean | string | undefined): string | undefined {
  if (cache === false) {
    return undefined;
  }
  return typeof cache === "string" ? cache : DEFAULT_CACHE;
}
