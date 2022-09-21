Module['_wait_run_dependencies'] = function() {
    const promise = new Promise((r) => {
        Module.monitorRunDependencies = (n) => {
            if (n === 0) {
                r();
            }
        };
    });
    Module.addRunDependency("dummy");
    Module.removeRunDependency("dummy");
    return promise;
}
