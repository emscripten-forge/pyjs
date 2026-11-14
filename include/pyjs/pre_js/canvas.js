// make `canvas` (HTMLCanvasElement or OffscreenCanvas) the canvas emscripten's
// GL / SDL / html5 code renders to: `Module.canvas` (SDL2, Browser) and the
// "#canvas" target (emscripten_webgl_create_context("#canvas"), html5 events)
Module['_set_canvas'] = function(canvas) {
    Module['canvas'] = canvas;
    if (typeof specialHTMLTargets !== "undefined") {
        specialHTMLTargets["#canvas"] = canvas;
    }
}
