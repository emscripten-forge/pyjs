# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Derived from pyodide's test plugin (pytest-pyodide), modified for pyjs.
"""What the tests ported from pyodide share.

Importing this module defines three JavaScript functions as globals, which
the JavaScript snippets of pyodide's tests use:

* ``assert(() => condition, message)``: throws unless the function returns
  exactly ``true``
* ``assertThrows(() => code, "ErrorClassName", /message pattern/)``: throws
  unless the function throws such an error
* ``assertThrowsAsync(async () => code, "ErrorClassName", pattern)``: the
  same for a rejected promise; to be awaited

In those snippets `pyjs` (the pyjs Module, a global set by the test page)
takes the place of pyodide's `pyodide` object.
"""

import pytest

from pyjs import jspi_enabled, run_js

run_js(
    """
    globalThis.assert = function (cb, message = "") {
        if (message !== "") {
            message = "\\n" + message;
        }
        if (cb() !== true) {
            throw new Error(`Assertion failed: ${cb.toString().slice(6)}${message}`);
        }
    };
    function checkError(err, errname, pattern, pat_str, thiscallstr) {
        if (typeof pattern === "string") {
            pattern = new RegExp(pattern);
        }
        if (!err) {
            throw new Error(`${thiscallstr} failed, no error thrown`);
        }
        if (err.constructor.name !== errname) {
            throw new Error(
                `${thiscallstr} failed, expected error of type '${errname}' got type '${err.constructor.name}': ${err.message}`
            );
        }
        if (!pattern.test(err.message)) {
            throw new Error(
                `${thiscallstr} failed, expected error message to match pattern ${pat_str} got:\\n${err.message}`
            );
        }
    }
    globalThis.assertThrows = function (cb, errname, pattern) {
        const pat_str = typeof pattern === "string" ? `"${pattern}"` : `${pattern}`;
        const thiscallstr = `assertThrows(${cb.toString()}, "${errname}", ${pat_str})`;
        let err = undefined;
        try {
            cb();
        } catch (e) {
            err = e;
        }
        checkError(err, errname, pattern, pat_str, thiscallstr);
    };
    globalThis.assertThrowsAsync = async function (cb, errname, pattern) {
        const pat_str = typeof pattern === "string" ? `"${pattern}"` : `${pattern}`;
        const thiscallstr = `assertThrowsAsync(${cb.toString()}, "${errname}", ${pat_str})`;
        let err = undefined;
        try {
            await cb();
        } catch (e) {
            err = e;
        }
        checkError(err, errname, pattern, pat_str, thiscallstr);
    };
    """
)

#: for tests that need JSPI (pyodide's `requires_jspi`)
requires_jspi = pytest.mark.skipif(not jspi_enabled(), reason="needs JSPI")
