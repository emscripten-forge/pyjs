import pyjs
import pyjs_core


def test_webgpu_in_runtime():
    """The runtime is linked with the emdawnwebgpu port (CMake option
    PYJS_WEBGPU): its JS side (`Module.WebGPU`) is part of the runtime, so
    side modules using webgpu.h can be loaded. Independent of the browser."""
    webgpu = pyjs_core._module.WebGPU
    assert webgpu is not None
    assert pyjs.js.Reflect.has(webgpu, "getJsObject")
