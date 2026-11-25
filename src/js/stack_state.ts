// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
//
// Derived from pyodide (src/core/stack_switching/stack_state.mjs, release
// 314.0.8), modified for pyjs. The other half (CPython's thread state) is
// src/stack_switching.c; see src/stack_switching_README.md.
//
// ---------------------------------------------------------------------------
// The C stack of several suspended Python calls.
//
// Compiled C code keeps part of its data (locals whose address is taken,
// big structs, CPython's C frames) not on the wasm call stack the browser
// manages, but on a stack in linear memory: emscripten's "C stack", one
// region with a stack pointer (stackSave() / stackRestore()). It grows DOWN.
//
// JSPI suspends the wasm call stack, but the browser knows nothing about this
// region. When a promising call (a "task") suspends, its data stays in the
// region, and the next task would overwrite it. So each suspended task gets a
// StackState: the address range it uses, [start, stop), and, if another task
// needed that space, a copy of the bytes (`copy`). Before a task resumes,
// restore() puts its bytes back (moving whatever is in the way to the copies
// of those tasks) and sets the stack pointer.
//
//                    |     ^^^       |
//                    |  older data   |
//      stop . . . .  |_______________|  (stack pointer when the task was entered)
//                    |               |
//                    |  data of this |
//                    |  task still   |
//                    |  in place     |
//                    |_______________|  . . . start + copy.length
//                    |               |       _____________
//                    | bytes another |      | bytes saved |
//                    | task needed   |      | in `copy`   |
//      start . . . . |_______________|  . . |_____________|
//                    |  newer data   |  (stack pointer when the task suspended)
//                    |     vvv       |
//
// A task is only ever entered or resumed at the event loop level: no wasm
// frame is running (callPythonPromising yields to the event loop first if
// necessary). So nothing else on the C stack is live at that moment except
// the data of other suspended tasks, which this file tracks.
// ---------------------------------------------------------------------------

/**
 * The tasks that have (part of) their data on the real C stack, except the one
 * running right now. Sorted: earlier entries are further up (higher
 * addresses), later entries further down.
 */
const stackStates: StackState[] = [];

/** stack pointer when the running task was entered (its `stop`) */
let stackStop = 0;

/** stack pointer of the very first task: the top of the whole stack */
let stackTop: number | undefined;

// running average of the stack size of a task (start value: one task of 500
// bytes, so no division by zero)
let taskSizeTotal = 500;
let taskSizeCount = 1;

/**
 * Move the data of every task out of the way that lies below `stop`, so that
 * the stack from `stop` downwards is free to use. `self` is a task about to
 * be restored: it is taken off the list, its bytes are not saved (they are
 * about to be put back anyway).
 */
function evictStackUpTo(stop: number, self?: StackState): void {
  if (self !== undefined) {
    const index = stackStates.lastIndexOf(self);
    if (index !== -1) {
      stackStates.splice(index, 1);
    }
  }
  // tasks entirely below `stop`: saved completely
  while (stackStates.length > 0 && stackStates[stackStates.length - 1].stop <= stop) {
    stackStates.pop()!.saveUpTo(Infinity);
  }
  // the lowest remaining one may reach below `stop`: its lower part is saved
  if (stackStates.length > 0) {
    stackStates[stackStates.length - 1].saveUpTo(stop);
  }
}

function setStackPosition(position: number): void {
  evictStackUpTo(position);
  stackRestore(position);
}

/**
 * Called right before a new task enters Python: choose where on the C stack
 * it runs and evict the tasks in the way. Then remember the stack pointer as
 * the new task's `stop`.
 *
 * A gap between suspended tasks that is big enough for a typical task is
 * used (searched from the bottom up: placing a task low is cheaper for short
 * tasks). Otherwise the task runs below the lowest suspended one; if the stack
 * pointer is already below that (a task higher up exited first), it is moved
 * up to it.
 */
export function enterTask(): void {
  if (stackTop === undefined) {
    // the first task: its stack pointer is the top of the whole stack
    stackTop = stackSave();
  } else {
    placeTask(stackTop);
  }
  stackStop = stackSave();
}

function placeTask(top: number): void {
  // Bigger threshold: more stack space used, less copying.
  const threshold = (taskSizeTotal / taskSizeCount) * 0.8;
  let lastStop = stackStates.length > 0 ? stackStates[stackStates.length - 1].stop : undefined;
  for (let index = stackStates.length - 2; index >= -1; index--) {
    const start = index >= 0 ? stackStates[index].start : top;
    if (lastStop !== undefined && start - lastStop > threshold) {
      setStackPosition(start);
      return;
    }
    lastStop = index >= 0 ? stackStates[index].stop : top;
  }
  const bottomUsed = stackStates.length > 0 ? stackStates[stackStates.length - 1].start : top;
  if (bottomUsed > stackSave()) {
    setStackPosition(bottomUsed);
  }
}

/** The C stack data of a suspended task (see the top of this file). */
export class StackState {
  /** stack pointer when the task suspended */
  start: number;
  /** stack pointer when the task was entered */
  stop: number;
  /** the bytes of [start, start + copy.length) another task needed */
  copy: Uint8Array = new Uint8Array(0);

  /** Called right before the running task suspends. */
  constructor() {
    this.start = stackSave();
    this.stop = stackStop;
    taskSizeTotal += this.stop - this.start;
    taskSizeCount += 1;
    if (this.start !== this.stop) {
      // (a task using no C stack at all needs no tracking)
      stackStates.push(this);
    }
  }

  /**
   * Called right after the task was resumed, before it continues: its bytes
   * back in place, the stack pointer where it was.
   */
  restore(): void {
    evictStackUpTo(this.stop, this);
    if (this.copy.length !== 0) {
      HEAPU8.set(this.copy, this.start);
      this.copy = new Uint8Array(0);
    }
    stackStop = this.stop;
    stackRestore(this.start);
  }

  /** copy the bytes of [start, min(stop, end)) that are not copied yet */
  saveUpTo(end: number): void {
    const size = Math.min(end, this.stop) - this.start;
    const saved = this.copy.length;
    if (size <= saved) {
      return;
    }
    const copy = new Uint8Array(size);
    copy.set(this.copy);
    copy.set(HEAPU8.subarray(this.start + saved, this.start + size), saved);
    this.copy = copy;
  }
}

/** for tests: the number of tasks with data on the C stack */
export function stackStateCount(): number {
  return stackStates.length;
}
