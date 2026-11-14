import pyjs


async def test_webgpu_device():
    """Request a WebGPU adapter + device from Python (awaiting the JS
    promises). Headless browsers / CI runners often have no WebGPU or no
    adapter: then there is nothing to test."""
    if not pyjs.js.Reflect.has(pyjs.js.navigator, "gpu"):
        print("skip test_webgpu_device: navigator.gpu is not available")
        return
    gpu = pyjs.js.navigator.gpu

    # needs no adapter
    assert gpu.getPreferredCanvasFormat() in ("bgra8unorm", "rgba8unorm")

    adapter = await gpu.requestAdapter()
    if adapter is None:
        print("skip adapter/device part of test_webgpu_device: no adapter")
        return

    device = await adapter.requestDevice()
    assert device is not None
    assert device.limits.maxComputeWorkgroupSizeX >= 1
    device.destroy()
