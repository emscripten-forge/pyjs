# JavaScript API

Running Python from JavaScript. `pyjs` below is what `initializePyjsRuntime`
of the [npm package](npm.md) returns (the emscripten `Module` with the pyjs
API). The names follow pyodide. Examples using numpy install it first with
`pyjs.installPackages` (solved and downloaded from emscripten-forge at runtime).

## Running code

### `runPython(code, options?)`

Run Python code and return the value of its last line if that is an
expression, like a notebook cell. A Python exception is thrown as
`PythonError`.

```javascript
pyjs.runPython("print('hello from python')");
pyjs.runPython("x = 20\nx + 1"); // 21
```

`options`: `globals` / `locals` (proxies of Python dicts: the namespaces the
code runs in, default `pyjs.globals`), `filename` (the file name in
tracebacks).

### `runPythonAsync(code, options?)`

The same for code with `await` at the top level; returns a promise.

```javascript
const result = await pyjs.runPythonAsync(`
import asyncio
await asyncio.sleep(0.1)
sum(range(100))
`);
console.log(result); // 4950
```

### `pyimport(name)`

`import name`: the Python module as proxy.

```javascript
const math = pyjs.pyimport("math");
console.log(math.sqrt(2)); // 1.4142135623730951
math.destroy();
```

### `globals`

The namespace code runs in by default (the globals of `__main__`), as a proxy
of the dict: `get`, `set`, `has`, `delete`.

```javascript
pyjs.globals.set("n", 7);
pyjs.runPython("n * 6"); // 42
```

### `toPy(value, options?)`

A JavaScript value as Python object (Python's `pyjs.to_py`): Array -> list,
Map / plain Object -> dict, Set -> set, ...

```javascript
const d = pyjs.toPy({ a: [1, 2, 3] });
pyjs.globals.set("d", d);
pyjs.runPython("sum(d['a'])"); // 6
d.destroy();
```

## Python objects in JavaScript: `PyProxy`

Numbers, strings, booleans and `None` (`undefined`) are converted when they
cross over; every other Python object is a `PyProxy` in JavaScript.

```javascript
await pyjs.installPackages(["numpy"]);
const arr = pyjs.runPython("import numpy\nnumpy.eye(2)");
console.log(arr.shape.toString());   // (2, 2)
console.log(arr.get(0).get(0));      // 1
const asList = arr.tolist().toJs();  // [[1, 0], [0, 1]]
arr.destroy();
```

| | |
|---|---|
| `proxy(...args)` | call it (an `async def` function is started as asyncio task) |
| `proxy.callKwargs(...args, {name: value})` | call it with keyword arguments |
| `await proxy.callPromising(...args)` | call it so that it may wait in `run_sync` (JSPI); Python starts in a later step of the event loop, not inside the call |
| `proxy.attr`, `proxy.attr = x` | attribute access |
| `proxy.get(key)`, `.set(key, value)`, `.has(key)`, `.delete(key)` | `obj[key]`, `key in obj`, `del obj[key]` |
| `for (const x of proxy)` | iterate |
| `await proxy` | await a coroutine / task / future |
| `proxy.toJs(options?)` | a deep copy as JavaScript values (list -> Array, dict -> Object, set -> Set, ...); `options` are the keyword arguments of Python's `to_js` (`{depth: 1}`, `{dict_converter: ...}`) |
| `proxy.copy()` | a second proxy of the same object |
| `proxy.destroy()` | release the Python object (the proxy is unusable afterwards) |

A proxy keeps its Python object alive until `destroy()` (or until the
JavaScript garbage collector collected the proxy: a backstop, not the plan).

## Errors

A Python exception reaching JavaScript is thrown as `PythonError`
(`pyjs.PythonError` for `instanceof`): `type` is the name of the exception
class (`"KeyError"`), `message` the formatted traceback.

```javascript
try {
  pyjs.runPython("{}['missing']");
} catch (e) {
  console.log(e instanceof pyjs.PythonError, e.type); // true KeyError
}
```

## Installing packages and files

`installPackages`, `unpackArchive`, `addFiles`, `saveBytecode`, `FS` (the
emscripten file system): see [npm package](npm.md).
