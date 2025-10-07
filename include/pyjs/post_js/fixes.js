if (!('wasmTable' in Module)) {
    Module['wasmTable'] = wasmTable
}

Module['FS'] = FS
Module['PATH'] = PATH
Module['LDSO'] = LDSO
Module['getDylinkMetadata'] = getDylinkMetadata
Module['loadDynamicLibrary'] = loadDynamicLibrary
Module['getPromise'] = getPromise
Module['promiseMap'] = promiseMap

Module['stackSave'] = stackSave
Module['stackRestore'] = stackRestore
Module['runtimeKeepalivePush'] = runtimeKeepalivePush
Module['UTF8ToString'] = UTF8ToString
Module['stringToUTF8OnStack'] = stringToUTF8OnStack