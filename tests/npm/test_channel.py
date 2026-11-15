import importlib
import sys

import pyjs
import pyjs_core


async def test_install_from_self_hosted_channel():
    """Install packages from a channel that is just static files on the page's
    origin (what a GitHub Pages deployment of CI-built packages looks like):
    the driver serves a generated channel at /test-channel/ with a noarch python
    package depending on an arch package (pyjs_test_driver/test_channel.py)."""
    channel = str(pyjs.js.location.origin) + "/test-channel"
    make_args = pyjs.js.Function(
        "spec", "channel", "return [[spec], {channels: [channel]}]"
    )
    args = make_args("pyjs-test-channel-py", channel)
    installed = pyjs.to_py(await pyjs_core._module.installPackages(args[0], args[1]))
    assert sorted(installed) == ["pyjs-test-channel-arch", "pyjs-test-channel-py"], installed

    importlib.invalidate_caches()
    import pyjs_test_channel

    assert pyjs_test_channel.VALUE == 42
    expected_arch = "wasm64" if sys.maxsize > 2**32 else "wasm32"
    assert pyjs_test_channel.arch_of_dependency() == expected_arch


async def test_self_hosted_channel_has_priority():
    """A package in the self-hosted channel wins over the same package in the
    default channels (listed after it), even with a much lower version: the
    channel generates `tabulate` 0.0.1, conda-forge has 0.9.x."""
    channel = str(pyjs.js.location.origin) + "/test-channel"
    make_args = pyjs.js.Function(
        "spec", "channel",
        "return [[spec], {channels: [channel, 'https://repo.prefix.dev/emscripten-forge/6x', 'conda-forge']}]",
    )
    args = make_args("tabulate", channel)
    installed = pyjs.to_py(await pyjs_core._module.installPackages(args[0], args[1]))
    assert "tabulate" in installed, installed

    importlib.invalidate_caches()
    import tabulate

    assert getattr(tabulate, "FROM_TEST_CHANNEL", False), tabulate.__file__
