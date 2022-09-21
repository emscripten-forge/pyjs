
Module['_IS_NODE'] = (typeof process === "object" && typeof require === "function")

Module['_IS_BROWSER_WORKER_THREAD'] = (typeof importScripts === "function")

Module['_IS_BROWSER_MAIN_THREAD'] = (typeof window === "object")
