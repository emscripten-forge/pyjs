# What is pyjs

`pyjs` is an library which allows to run Python code in the browser or in node.
Why not just compile the python executable to wasm and use this?

## aa

# wup

The usage from
```JavaScript
import {createModule} from '../pyjs_runtime_browser.js';
let pyjs = await createModule()
globalThis.pyjs = pyjs
```


```python
from pyjs.js import console

console.log("print to browser console")
```
