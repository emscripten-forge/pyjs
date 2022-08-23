# Usage

This describes the overall workflow to setup an `emscripten-32` environment with `micromamba`, packing this environment with `empack` and use this environment with `pyjs`.

## Install micromamba

We strongly recommend to use micromamba when using `pyjs`.
Please refer to the [mamba and micromamba installation guide in the documentation.](https://mamba.readthedocs.io/en/latest/installation.html)

## Create the working environment

First we create an environment containing all the dev-dependencies.

```yaml
name: pyjs-dev-env
channels:
  - conda-forge
dependencies:
  - python
  - curl
  - empack >= 1.2.0
  - emsdk >=3.1.11
```

Assuming the yaml file above is named `pyjs-dev-env.yaml`, we can create the dev-environment with:

```bash
micromamba create \
    --yes --file  pyjs-dev-env.yaml  \
    -c https://repo.mamba.pm/emscripten-forge \
    -c https://repo.mamba.pm/conda-forge
```


## Create the web environment

This is the environment which will be available  from the browser / nodejs.

```yaml
name: pyjs-wasm-env
channels:
  - https://repo.mamba.pm/emscripten-forge
  - conda-forge
dependencies:
  - pyjs == 0.11.1
  - numpy
  - pyb2d
```
Assuming the yaml file above is named `pyjs-wasm-env.yaml`, we can create the web-environment with:

```Bash
micromamba create \
    --platform=emscripten-32 \
    --yes --file  pyjs-wasm-env.yaml  \
    -c https://repo.mamba.pm/emscripten-forge \
    -c https://repo.mamba.pm/conda-forge
```


## Pack the environment

First we download the empack default configuration [github](https://raw.githubusercontent.com/emscripten-forge/recipes/main/empack_config.yaml)
```bash
curl https://raw.githubusercontent.com/emscripten-forge/recipes/main/empack_config.yaml --output empack_config.yaml
```

Next we invoke empack to pack the conda-environment `pyjs-wasm-env` into `*.data/*.js` files which can be fetched and imported from JavaScript.

```bash
empack pack env \
    --env-prefix $MAMBA_ROOT_PREFIX/envs/pyjs-wasm-env \
    --outname my_sample_application \
    --config empack_config.yaml \
    --config extra_config.yaml  \
    --outdir output \
    --export-name globalThis.pyjs \
    --split
````


## Use It
Now that we packed our environment in (multiple) JavaScript files, we can start using `pyjs`:

### Initialize pyjs

The initialization of pyjs in JavaScript unfortunately still a bit complicated:

```JavaScript
// pyjs itself
import {createModule} from '../pyjs_runtime_browser.js';
let pyjs = await createModule()
globalThis.pyjs = pyjs

// content of the packaged wasm environment
const { default: load_all }  = await import('../my_sample_application.js')
await load_all()
await pyjs.init()

```


### Use Pyjs

The initialization of pyjs in JavaScript unfortunately still a bit complicated:

```JavaScript
// pyjs itself
pysjs.exec(`
import numpy
print(numpy.zeros([10,20]))
`)
```


Within the python code called from JavaScript, one has access to the `pyjs` python module.
This allows access to the JavaScript side from Python:


```python
from pyjs.js import console

console.log("print to browser console")
```
