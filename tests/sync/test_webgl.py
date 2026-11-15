import ctypes

import pyjs
import pyjs_core


GL_COLOR_BUFFER_BIT = 0x4000
GL_VERSION = 0x1F02
GL_NO_ERROR = 0


class _WebGLContextAttributes(ctypes.Structure):
    """`EmscriptenWebGLContextAttributes` (emscripten/html5_webgl.h)."""

    _fields_ = [
        ("alpha", ctypes.c_bool),
        ("depth", ctypes.c_bool),
        ("stencil", ctypes.c_bool),
        ("antialias", ctypes.c_bool),
        ("premultipliedAlpha", ctypes.c_bool),
        ("preserveDrawingBuffer", ctypes.c_bool),
        ("powerPreference", ctypes.c_int),
        ("failIfMajorPerformanceCaveat", ctypes.c_bool),
        ("majorVersion", ctypes.c_int),
        ("minorVersion", ctypes.c_int),
        ("enableExtensionsByDefault", ctypes.c_bool),
        ("explicitSwapControl", ctypes.c_bool),
        ("proxyContextToMainThread", ctypes.c_int),
        ("renderViaOffscreenBackBuffer", ctypes.c_bool),
        ("desynchronized", ctypes.c_bool),
    ]


def _new_canvas():
    """A canvas usable in the main thread (DOM canvas) and in a worker
    (OffscreenCanvas); None if neither exists."""
    if pyjs.js.Reflect.has(pyjs.js.globalThis, "document"):
        canvas = pyjs.js.document.createElement("canvas")
        canvas.width = 64
        canvas.height = 64
        return canvas
    if pyjs.js.Reflect.has(pyjs.js.globalThis, "OffscreenCanvas"):
        return pyjs.new(pyjs.js.OffscreenCanvas, 64, 64)
    return None


def test_webgl2_in_runtime():
    """The runtime is linked with WebGL2 / GLES 3 (CMake option PYJS_WEBGL):
    WebGL2-only GL functions are part of it. Independent of the browser."""
    assert pyjs_core._module.GL is not None
    assert pyjs_core._module._glVertexAttribIPointer is not None
    assert pyjs_core._module._glDrawArraysInstanced is not None


def test_sdl2_in_runtime():
    """The runtime is linked with the SDL2 port (CMake option PYJS_SDL2)."""
    assert pyjs_core._module._SDL_CreateWindow is not None
    assert pyjs_core._module._SDL_GL_CreateContext is not None


def test_gl_functions_via_ctypes():
    """GL functions (implemented in JS by emscripten) can be looked up from the
    main module with dlsym, as ctypes-based bindings (PyOpenGL) do."""
    lib = ctypes.CDLL(None)
    for name in ("glClear", "glClearColor", "glGetError", "glGetString",
                 "glVertexAttribIPointer", "emscripten_webgl_create_context"):
        assert getattr(lib, name) is not None, name


def test_webgl2_context_via_ctypes():
    """Create a WebGL2 context on a canvas set with `pyjs.set_canvas` and call
    GL through ctypes. Skips when the browser gives no WebGL2 context."""
    canvas = _new_canvas()
    if canvas is None:
        print("skip test_webgl2_context_via_ctypes: no canvas")
        return
    pyjs.set_canvas(canvas)

    lib = ctypes.CDLL(None)
    attrs = _WebGLContextAttributes()
    lib.emscripten_webgl_init_context_attributes(ctypes.byref(attrs))
    attrs.majorVersion = 2
    attrs.minorVersion = 0

    create = lib.emscripten_webgl_create_context
    create.restype = ctypes.c_size_t
    create.argtypes = [ctypes.c_char_p, ctypes.POINTER(_WebGLContextAttributes)]
    ctx = create(b"#canvas", ctypes.byref(attrs))
    if ctx == 0:
        print("skip test_webgl2_context_via_ctypes: no WebGL2 context")
        return

    make_current = lib.emscripten_webgl_make_context_current
    make_current.argtypes = [ctypes.c_size_t]
    assert make_current(ctx) == 0  # EMSCRIPTEN_RESULT_SUCCESS
    try:
        lib.glClearColor.argtypes = [ctypes.c_float] * 4
        lib.glClearColor(0.0, 0.5, 1.0, 1.0)
        lib.glClear(GL_COLOR_BUFFER_BIT)
        assert lib.glGetError() == GL_NO_ERROR

        lib.glGetString.restype = ctypes.c_char_p
        version = lib.glGetString(GL_VERSION)
        assert version.startswith(b"OpenGL ES 3.0"), version
    finally:
        destroy = lib.emscripten_webgl_destroy_context
        destroy.argtypes = [ctypes.c_size_t]
        destroy(ctx)
