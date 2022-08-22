# workflow

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

```bash
micromamba create \
    --platform=emscripten-32 \
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


```Bash
micromamba create \
    --platform=emscripten-32 \
    --yes --file  pyjs-wasm-env.yaml  \
    -c https://repo.mamba.pm/emscripten-forge \
    -c https://repo.mamba.pm/conda-forge
```
