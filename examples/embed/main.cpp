// The program itself does nothing: python is started from JavaScript
// (Module.startPython() in run.js), after the file system is filled. A real
// embedder would have its own code here and could use python's C API once
// python runs.
int main()
{
    return 0;
}
