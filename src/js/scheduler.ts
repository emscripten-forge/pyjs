// The queue everything that enters Python "later" goes through (adapted from
// pyodide's src/js/scheduler.ts, MPL-2.0).
//
// `scheduleCallback(callback)` runs `callback` in a later task of the event
// loop (a macrotask: the browser can render and handle events in between), as
// soon as possible and in the order of the calls. Three things use it:
//   - WebLoop.call_soon (module/pyjs/webloop.py): every step of an asyncio task
//   - `proxy.callPromising(...)`: a task starts in a later step, never inside
//     the call (callPythonPromising, pyproxy.ts)
//   - and with that, the stack suspended in `pyjs.run_sync`: it waits for an
//     asyncio future, whose callbacks are call_soon callbacks (core.py)
// ONE queue for all of them is the point: Python code continues in the order
// in which things became ready. With separate mechanisms (a microtask here, a
// message there, a timer elsewhere) that order changes whenever the page was
// busy and several are due at once.
//
// How: one message on a private MessageChannel per callback (in node:
// setImmediate). Not `setTimeout(callback, 0)`: browsers clamp nested timeouts
// to >= 4 ms. Safari is excluded (MessageChannel is slow there and disturbs
// its event loop, see pyodide#4583) and falls back to setTimeout.
//
// Nothing of this is visible from the outside (no global, nothing exported
// from the package): only the loop and the proxies use it.

const queue: Array<() => void> = [];

/** queues one run of `runNext` in a later task; null: no fast way here */
const post: (() => void) | null = (() => {
  const proc = (globalThis as any).process;
  if (typeof proc === "object" && proc?.versions?.node) {
    const setImmediate = (globalThis as any).setImmediate;
    return typeof setImmediate === "function" ? () => setImmediate(runNext) : null;
  }
  const nav = (globalThis as any).navigator;
  const userAgent = typeof nav === "object" && typeof nav?.userAgent === "string" ? nav.userAgent : "";
  const isSafari = userAgent.indexOf("Chrome") === -1 && userAgent.indexOf("Safari") > -1;
  if (isSafari || typeof MessageChannel !== "function") {
    return null;
  }
  const channel = new MessageChannel();
  channel.port1.onmessage = runNext;
  return () => channel.port2.postMessage(undefined);
})();

/** one callback per task, in the order they were scheduled */
function runNext(): void {
  queue.shift()!();
}

/** run `callback` in a later task of the event loop, in the order of the calls */
export function scheduleCallback(callback: () => void): void {
  if (post === null) {
    setTimeout(callback, 0);
    return;
  }
  queue.push(callback);
  post();
}
