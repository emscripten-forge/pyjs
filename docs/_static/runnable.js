// Run buttons for the Python and JavaScript code snippets of the docs.
//
// pyjs itself runs them: the npm package built from this repository is
// deployed next to the html (<html root>/pyjs/, see build_local.sh docs) and
// loaded on the first click. Python snippets share one scope per page (like a
// notebook), JavaScript snippets get `pyjs` (the initialized runtime). The
// boxes are editable. Snippets install the packages they need themselves
// (`await pyjs.installPackages([...])`), nothing is guessed.

const ROOT = new URL(document.documentElement.dataset.content_root ?? "./", location.href);
const PACKAGE_URL = new URL("pyjs/dist/index.js", ROOT).href;

// snippets about loading pyjs itself (npm / CDN imports, initialization)
// cannot run inside a page that already has pyjs
const NOT_RUNNABLE = [/^\s*import\s.*\sfrom\s/m, /initializePyjsRuntime\(/, /^\s*npm\s/m];

let pyjsPromise;
// the output element of the snippet that currently runs (python print goes there)
let currentOutput = null;

/** append a line to the output of the running snippet */
function write(text, kind = "") {
  if (!currentOutput) return console.log(text);
  const line = document.createElement("div");
  line.className = kind;
  line.textContent = text;
  currentOutput.append(line);
}

/** the pyjs runtime of this page (created on first use) */
function getPyjs() {
  pyjsPromise ??= import(PACKAGE_URL).then(({ initializePyjsRuntime }) =>
    initializePyjsRuntime({
      print: (text) => write(text),
      printErr: (text) => write(text, "pyjs-run-error"),
    })
  );
  return pyjsPromise;
}

/** a readable message for JS errors and python errors ({has_err, ...}) */
function errorText(e) {
  if (e && typeof e === "object" && "has_err" in e) return `${e.error ?? ""}\n${e.message ?? ""}`.trim();
  return String((e && e.stack) || e);
}

/** show a result value (the last expression) like a REPL */
function show(value) {
  if (value === undefined || value === null) return;
  let text;
  try {
    text = typeof value === "string" ? JSON.stringify(value) : String(value);
  } catch {
    text = Object.prototype.toString.call(value);
  }
  write(text, "pyjs-run-result");
}

/** run one snippet, output below it */
async function run(language, code, output, button) {
  output.replaceChildren();
  output.hidden = false;
  currentOutput = output;
  button.disabled = true;
  // console output of the snippet (e.g. `pyjs.js.console.log(...)`) goes below it too
  const consoleLog = console.log;
  console.log = (...args) => {
    consoleLog(...args);
    write(args.map(String).join(" "));
  };
  try {
    if (!pyjsPromise) write("loading pyjs ...", "pyjs-run-info");
    const pyjs = await getPyjs();
    if (language === "python") {
      show(await pyjs.async_exec_eval(code));
    } else {
      // top level await allowed, `pyjs` in scope
      const AsyncFunction = (async () => {}).constructor;
      show(await new AsyncFunction("pyjs", code)(pyjs));
    }
    if (!output.childElementCount) write("(no output)", "pyjs-run-info");
  } catch (e) {
    write(errorText(e), "pyjs-run-error");
  } finally {
    console.log = consoleLog;
    currentOutput = null;
    button.disabled = false;
  }
}

/** make a code box editable in place (plain text, Tab = 4 spaces) */
function makeEditable(pre, onRun, onEdit) {
  pre.contentEditable = "plaintext-only";
  // browsers without plaintext-only keep it read-only
  if (pre.contentEditable !== "plaintext-only") return;
  pre.spellcheck = false;
  pre.classList.add("pyjs-editable");
  pre.addEventListener("input", onEdit);
  pre.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      onRun();
    } else if (e.key === "Tab") {
      e.preventDefault();
      document.execCommand("insertText", false, "    ");
    } else if (e.key === "Enter") {
      // a plain newline (no <br> / <div> from the browser)
      e.preventDefault();
      document.execCommand("insertText", false, "\n");
    }
  });
}

/** run + reset buttons and an output area for every runnable python / js snippet */
function addRunButtons() {
  const blocks = document.querySelectorAll(
    "div.highlight-python, div.highlight-javascript, div.highlight-js"
  );
  for (const block of blocks) {
    const language = block.classList.contains("highlight-python") ? "python" : "javascript";
    const pre = block.querySelector("pre");
    const original = pre.innerHTML;  // with the syntax highlighting, for reset
    if (NOT_RUNNABLE.some((pattern) => pattern.test(pre.textContent))) continue;

    const bar = document.createElement("div");
    bar.className = "pyjs-run-bar";
    const button = document.createElement("button");
    button.className = "pyjs-run-button";
    button.textContent = "▶ Run";
    button.title = `run this ${language} snippet with pyjs, in your browser (Ctrl+Enter)`;
    const reset = document.createElement("button");
    reset.className = "pyjs-reset-button";
    reset.textContent = "Reset";
    reset.title = "restore the original code";
    reset.hidden = true;
    bar.append(button, reset);
    const output = document.createElement("div");
    output.className = "pyjs-run-output";
    output.hidden = true;

    // always the current content of the box (it is editable)
    const runIt = () => run(language, pre.innerText, output, button);
    button.addEventListener("click", runIt);
    reset.addEventListener("click", () => {
      pre.innerHTML = original;
      reset.hidden = true;
    });
    makeEditable(pre, runIt, () => { reset.hidden = false; });
    block.after(bar, output);
  }
}

addRunButtons();
