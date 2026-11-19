"""Plain-English hints from a Comparison. Deterministic: no AI, no network."""

from __future__ import annotations

import ast
import inspect
import linecache
import re
import textwrap
from typing import List

from .tracer import RAISE, RETURN

_MAX_HINTS = 5


def _exception_hint(text: str) -> str:
    m = re.match(r"ValueError: invalid literal for int\(\) with base 10: '(.*)'", text)
    if m:
        bad = m.group(1)
        extra = " Negative numbers contain a '-' when you loop over str(number); take abs() first." if bad == "-" else ""
        return "int() was given %r, which is not a string of digits.%s" % (bad, extra)
    m = re.match(r"AttributeError: 'NoneType' object has no attribute '(\w+)'", text)
    if m:
        return (
            "A variable is None when you call .%s on it. A common cause is assigning the result of a "
            "method that works in place (list.remove, append, sort, reverse), which returns None." % m.group(1)
        )
    if text.startswith("IndexError"):
        return "An index went past the end of a list. Check your loop bounds, and whether you remove items while looping."
    if text.startswith("KeyError"):
        return "A dictionary key was missing. Check the keys you add, or use .get()."
    if text.startswith("ZeroDivisionError"):
        return "Something was divided by zero. Check the case where the divisor can be 0."
    return ""


def generate(cmp) -> List[str]:
    """Return up to a few short hints about the candidate's behaviour."""
    out: List[str] = []
    d = cmp.divergence
    traces = [cmp.candidate]
    probe = getattr(cmp, "probe", None)
    if probe is not None and probe.minimal_candidate is not None:
        traces.append(probe.minimal_candidate)  # the smallest failing run is the clearest evidence

    for trace in traces:
        for ev in trace.history(RAISE):
            hint = _exception_hint(ev.value)
            if hint:
                out.append(hint)
        # A list that suddenly turns into None: the result of an in-place method was assigned back.
        for var in sorted(trace.variables):
            hist = trace.history(var)
            for prev, cur in zip(hist, hist[1:]):
                if cur.value == "None" and prev.value.startswith(("[", "{")):
                    src = linecache.getline(cur.filename, cur.lineno).strip()
                    out.append(
                        "'%s' was a collection but became None at line %d%s. Methods like remove/append/sort "
                        "change the object in place and return None, so do not assign their result back."
                        % (var, cur.lineno, (" (`%s`)" % src) if src else "")
                    )
                    break

    name_of = cmp.candidate.arg_names
    if d is not None and d.var.startswith("<arg"):
        out.append(
            "The input '%s' ends up different from the reference. If the task says to modify it in place, "
            "change the object itself; rebinding the name to a new object does not affect the caller."
            % name_of.get(d.var, "an argument")
        )
    if d is not None and d.var == RETURN and d.candidate is not None and d.candidate.value == "None":
        out.append("Your function returned None. Does every path end with `return <value>`?")

    out.extend(_source_hints(cmp))
    seen, unique = set(), []
    for h in out:
        if h and h not in seen:
            seen.add(h)
            unique.append(h)
    return unique[:_MAX_HINTS]


def _source_hints(cmp) -> List[str]:
    """Hints that come from reading the candidate's source code."""
    try:
        lines, first = inspect.getsourcelines(cmp.candidate_fn)
        tree = ast.parse(textwrap.dedent("".join(lines)))
        fn = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
    except (OSError, TypeError, SyntaxError, StopIteration):
        return []
    params = [a.arg for a in fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs]
    out = []
    for node in ast.walk(fn):
        line = first + getattr(node, "lineno", 1) - 1
        # for ... else without a break: the else block always runs
        if isinstance(node, (ast.For, ast.While)) and node.orelse:
            if not any(isinstance(n, ast.Break) for b in node.body for n in ast.walk(b)):
                out.append(
                    "Line %d: a loop has an `else:` block but no `break`. A loop's `else` runs whenever the "
                    "loop finishes without break, so here it always runs; it is not the 'otherwise' of an `if`." % line
                )
        # alias = parameter: does not copy a list/dict/set
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Name)
            and node.value.id in params
        ):
            idx = params.index(node.value.id)
            if idx < len(cmp.args) and isinstance(cmp.args[idx], (list, dict, set)):
                out.append(
                    "Line %d: `%s = %s` does not copy. Both names point to the same %s, so changing one changes "
                    "the other. Use a copy (for example `list(%s)`) if you need the original."
                    % (line, node.targets[0].id, node.value.id, type(cmp.args[idx]).__name__, node.value.id)
                )
    return out
