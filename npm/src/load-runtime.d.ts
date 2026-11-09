/** load the emscripten runtime module (`export default createModule`) */
export default function loadRuntime(url: string): Promise<{ default: (moduleArg?: Record<string, unknown>) => Promise<any> }>;
