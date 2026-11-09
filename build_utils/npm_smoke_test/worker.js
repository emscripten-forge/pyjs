// module worker: same checks as in the main thread
import { run } from "./test.js";

self.onmessage = async (e) => {
  let result;
  try {
    result = await run(e.data);
  } catch (err) {
    result = { ok: false, error: String((err && err.stack) || err) };
  }
  self.postMessage(result);
};
