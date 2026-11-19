"""Built-in sanity check. Run ``python -m difffinder`` or, in a notebook, ``difffinder.selfcheck()``.

It tests the things that matter on a hosted notebook server: tracing works, functions defined in
notebook cells (which have no real file on disk) are traced and shown with their source lines, the
HTML output renders, and the package has no dependencies that could conflict with the server's.
"""

from __future__ import annotations

import builtins
import linecache
import platform
import sys

_CELL = '''
def candidate(n):
    total = 0
    for i in range(n):
        total += i
    return total

def reference(n):
    total = 0
    for i in range(n + 1):
        total += i
    return total

def sort_bad(xs):
    xs = xs.sort()
    return xs

def sort_good(xs):
    xs.sort()
    return xs
'''

# How Jupyter names the code of a cell, depending on the IPython/ipykernel version.
_CELL_NAMES = (("<ipython-input-1-difffinder>", "older IPython"), ("/tmp/ipykernel_1/difffinder.py", "ipykernel"))


def _as_notebook_cell(source: str, filename: str) -> dict:
    """Compile like a notebook does: no file on disk, source kept only in linecache."""
    linecache.cache[filename] = (len(source), None, source.splitlines(True), filename)
    namespace: dict = {}
    exec(compile(source, filename, "exec"), namespace)
    return namespace


def selfcheck(verbose: bool = True) -> bool:
    """Run the checks, print a report, and return True if every check passed."""
    from . import __version__, compare_traces, find_difference

    results = []

    def check(name: str, ok: bool) -> None:
        results.append((name, bool(ok)))

    shell = getattr(builtins, "get_ipython", lambda: None)()
    where = "Jupyter/IPython (%s)" % type(shell).__name__ if shell is not None else "plain Python"
    try:
        for filename, label in _CELL_NAMES:
            ns = _as_notebook_cell(_CELL, filename)
            cmp = compare_traces(ns["candidate"], ns["reference"], args=(4,))
            d = cmp.divergence
            check("finds the off-by-one loop in a notebook cell (%s)" % label, d is not None and d.var == "i" and d.position == 4)
            check("shows the cell's source line (%s)" % label, "range(n + 1)" in str(cmp))
            check("shrinks to the smallest failing input (%s)" % label, cmp.probe is not None and cmp.probe.minimal == (1,))
        bad = compare_traces(ns["sort_bad"], ns["sort_good"], args=([3, 1, 2],))
        check("explains a list that became None", any("None" in h for h in bad.hints))
        check("renders HTML for notebooks", "<table" in cmp._repr_html_())
        hit = find_difference(ns["candidate"], ns["reference"], [0, 1, 2])
        check("find_difference returns the first differing input", hit is not None and hit.args == (1,))  # n=0 gives 0 in both
    finally:
        for filename, _ in _CELL_NAMES:
            linecache.cache.pop(filename, None)

    try:
        from importlib import metadata

        # Optional extras (dev, hermes) are only installed on request, so they do not count.
        required = [r for r in (metadata.requires("difffinder") or []) if "extra ==" not in r]
        check("has no required dependencies, so it cannot conflict with the server's packages", not required)
    except Exception:  # running from a source folder: no installed metadata to inspect
        pass

    passed = all(ok for _, ok in results)
    if verbose:
        print("difffinder %s | Python %s | %s | %s" % (__version__, platform.python_version(), platform.system(), where))
        for name, ok in results:
            print("  %s  %s" % ("PASS" if ok else "FAIL", name))
        print("All %d checks passed." % len(results) if passed else "Some checks FAILED. Please report the lines above.")
    return passed
