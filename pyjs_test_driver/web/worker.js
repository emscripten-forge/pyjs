// Module worker of the page contract: runs the suite with the pyjs of
// ./page.js, sends the console output and the result to the page.
import { runSuite } from "./harness.js";
import { createPyjs } from "./page.js";

// the driver listens on the page: forward the console of the worker
for (const level of ["log", "info", "warn", "error"]) {
  console[level] = (...args) => self.postMessage({ console: level, text: args.map(String).join(" ") });
}

self.onmessage = async ({ data: options }) => {
  self.postMessage({ result: await runSuite(createPyjs, options) });
};
