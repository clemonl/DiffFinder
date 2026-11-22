"""Black-box testing: find inputs where two functions disagree, shrink one, and describe the pattern.

This works however differently the two functions are written, because it only looks at what each one
visibly does (return value, exception, and what it did to its arguments), never at their internals.
"""

from __future__ import annotations

import contextlib
import copy
import io
import random
from dataclasses import dataclass, field
from itertools import combinations, zip_longest
from typing import Any, Dict, List, Optional

from .tracer import RAISE, RETURN, Trace, record
from .values import same_repr

MAX_SINGLES = 55  # inputs made by changing one argument
MAX_PAIRS = 25  # inputs made by changing two arguments at once
SHRINK_BUDGET = 150
STEP_LIMIT = 20_000


def _isnum(x: Any) -> bool:
    return type(x) in (int, float)  # bool is not a number here


def outcome(trace: Trace) -> tuple:
    """What a call visibly did. Exceptions count by type only, so message wording is not a difference."""
    items = []
    for e in trace.events:
        if e.var.startswith("<"):
            items.append((e.var, e.value.split(":")[0] if e.var == RAISE else e.value))
    if trace.truncated:
        items.append(("<timeout>", ""))
    return tuple(items)


def run_pair(candidate, reference, args, kwargs, tolerance=None):
    """Run both functions on copies of ``args``. Returns (candidate trace, reference trace, differ)."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        ta = record(candidate, copy.deepcopy(args), copy.deepcopy(kwargs), max_steps=STEP_LIMIT)
        tb = record(reference, copy.deepcopy(args), copy.deepcopy(kwargs), max_steps=STEP_LIMIT)
    outcomes_a, outcomes_b = outcome(ta), outcome(tb)
    differ = len(outcomes_a) != len(outcomes_b) or any(
        name_a != name_b
        or not (
            value_a == value_b
            if name_a == RAISE
            else same_repr(value_a, value_b, tolerance)
        )
        for (name_a, value_a), (name_b, value_b) in zip(outcomes_a, outcomes_b)
    )
    return ta, tb, differ


def _unique(seq, original) -> list:
    seen, out = {repr(original)}, []
    for item in seq:
        r = repr(item)
        if r not in seen:
            seen.add(r)
            out.append(item)
    return out


def _alternatives(value) -> list:
    """Interesting variations of one argument: edge cases and small mutations."""
    t, out = type(value), []
    if t is bool:
        out = [not value]
    elif t is int:
        out = [0, 1, -1, 2, -2, value + 1, value - 1, -value, value * 2, 10, 100]
    elif t is float:
        out = [0.0, 1.0, -1.0, -value, value + 1, value / 2]
    elif t is str:
        out = ["", "a", "ab", "aa", value[:1], value[:-1], value[::-1], value.upper(), " "]
    elif t in (list, tuple):
        items, make = list(value), t
        out = [make()]
        out += [make(items[:i] + items[i + 1 :]) for i in range(min(len(items), 6))]
        if items:
            out += [make(items[::-1]), make(items[:1]), make(items + items[:1])]
            try:
                out.append(make(sorted(items)))
            except TypeError:
                pass
        if not items or any(_isnum(x) for x in items):
            out += [make(items + [e]) for e in (0, -1, -3)]
            if items and all(_isnum(x) for x in items):
                out.append(make([-x for x in items]))
        for i in range(min(len(items), 4)):
            out += [make(items[:i] + [alt] + items[i + 1 :]) for alt in _alternatives(items[i])[:3]]
    elif t is dict:
        out = [{}] + [{k: v for k, v in value.items() if k != key} for key in list(value)[:4]]
    return _unique(out, value)


def _variants(args: tuple) -> List[tuple]:
    rng = random.Random(0)  # fixed seed: the same input always gives the same report
    groups = [[args[:i] + (alt,) + args[i + 1 :] for alt in _alternatives(a)] for i, a in enumerate(args)]
    seen, out = {repr(args)}, []

    def add(candidate):
        r = repr(candidate)
        if r not in seen:
            seen.add(r)
            out.append(candidate)

    for row in zip_longest(*groups):
        for c in row:
            if c is not None:
                add(c)
    del out[MAX_SINGLES:]
    changeable = [(i, _alternatives(a)) for i, a in enumerate(args)]
    changeable = [(i, alts) for i, alts in changeable if alts]
    if len(changeable) >= 2:
        for _ in range(MAX_PAIRS):
            (i, ai), (j, aj) = rng.sample(changeable, 2)
            c = list(args)
            c[i], c[j] = rng.choice(ai), rng.choice(aj)
            add(tuple(c))
    return out


def _shrinks(value) -> list:
    """Simpler versions of one argument, simplest first."""
    t, out = type(value), []
    try:
        if t is bool:
            out = [False] if value else []
        elif t is int:
            out = [0, int(value / 2), value - (1 if value > 0 else -1)] if value else []
        elif t is float:
            out = [0.0, float(round(value)), value / 2] if value else []
        elif t in (list, tuple, str):
            n = len(value)
            if n:
                out.append(value[:0])
            if n >= 4:
                out += [value[: n // 2], value[n // 2 :]]
            out += [value[:i] + value[i + 1 :] for i in range(n)]
            if t is not str:
                for i, x in enumerate(value):
                    out += [t(list(value[:i]) + [s] + list(value[i + 1 :])) for s in _shrinks(x)[:2]]
        elif t is dict:
            out = [{}] + [{k: v for k, v in value.items() if k != key} for key in value]
    except (ValueError, OverflowError):
        out = []
    return _unique(out, value)


def _shrink(candidate, reference, args, kwargs, ta, tb, tolerance=None):
    """Greedily simplify a failing input while the two functions still disagree."""
    best, spent, improved = args, 0, True
    while improved and spent < SHRINK_BUDGET:
        improved = False
        for i, a in enumerate(best):
            for s in _shrinks(a):
                if spent >= SHRINK_BUDGET:
                    break
                trial = best[:i] + (s,) + best[i + 1 :]
                spent += 1
                t1, t2, bad = run_pair(candidate, reference, trial, kwargs, tolerance)
                if bad:
                    best, ta, tb, improved = trial, t1, t2, True
                    break
            if improved:
                break
    return best, ta, tb


def _features(args: tuple, names: List[str]) -> Dict[str, bool]:
    """Simple yes/no facts about an input, used to describe when the functions disagree."""
    f: Dict[str, bool] = {}
    scalars = [(n, a) for n, a in zip(names, args) if _isnum(a)]
    for n, a in zip(names, args):
        tag = "`%s`" % n
        if type(a) in (list, tuple):
            items = list(a)
            nums = [x for x in items if _isnum(x)]
            f[tag + " is empty"] = not items
            f[tag + " has exactly one element"] = len(items) == 1
            f[tag + " has more than one element"] = len(items) > 1
            f[tag + " has repeated elements"] = len({repr(x) for x in items}) < len(items)
            if nums:
                f[tag + " contains a negative number"] = any(x < 0 for x in nums)
                f[tag + " contains 0"] = any(x == 0 for x in nums)
                for m, s in scalars:
                    f["%s contains a number below `%s`" % (tag, m)] = any(x < s for x in nums)
                    f["%s contains a number above `%s`" % (tag, m)] = any(x > s for x in nums)
                    f["%s contains a number equal to `%s`" % (tag, m)] = any(x == s for x in nums)
        elif type(a) is str:
            f[tag + " is empty"] = not a
            f[tag + " has exactly one character"] = len(a) == 1
            f[tag + " contains a digit"] = any(c.isdigit() for c in a)
            f[tag + " contains an upper-case letter"] = any(c.isupper() for c in a)
            f[tag + " contains a space"] = " " in a
        elif _isnum(a):
            f[tag + " is negative"] = a < 0
            f[tag + " is 0"] = a == 0
            f[tag + " is positive"] = a > 0
        elif type(a) is dict:
            f[tag + " is empty"] = not a
    for (m, x), (n, y) in combinations(scalars, 2):
        f["`%s` is greater than `%s`" % (m, n)] = x > y
        f["`%s` equals `%s`" % (m, n)] = x == y
    return f


def find_patterns(rows, names: List[str], limit: int = 2) -> List[str]:
    """Describe, from the inputs tried, a simple property that goes with the functions disagreeing."""
    failed = sum(1 for _, bad in rows if bad)
    if not failed or failed == len(rows):
        return []
    table = [(_features(a, names), bad) for a, bad in rows]
    keys: List[str] = []
    for feats, _ in table:
        keys += [k for k in feats if k not in keys]
    scored = []
    for k in keys:
        tp = sum(1 for f, bad in table if f.get(k) and bad)
        total = sum(1 for f, _ in table if f.get(k))
        if tp >= 2 and tp / total >= 0.85 and tp / failed >= 0.5:
            scored.append((tp / total, tp / failed, k, tp, total))
    scored.sort(key=lambda s: (-s[0], -s[1], len(s[2])))
    return [
        "It %s %s (%d of %d such inputs I tried)." % ("fails whenever" if p == 1 else "usually fails when", k, tp, total)
        for p, _, k, tp, total in scored[:limit]
    ]


def _returned(trace: Trace):
    hist = trace.history(RETURN)
    return hist[-1].value if hist else None


def _raised(trace: Trace):
    hist = trace.history(RAISE)
    return hist[-1].value.split(":")[0] if hist else None


def find_systematic(pairs, failing: int) -> List[str]:
    """Spot differences that hold on (almost) every input, which point to a basic mistake."""
    tried = len(pairs)
    got = [(_returned(a), _returned(b)) for a, b in pairs]
    both = [(x, y) for x, y in got if x is not None and y is not None]
    out: List[str] = []
    if len(both) >= 3 and all(x in ("True", "False") and y in ("True", "False") and x != y for x, y in both):
        out.append(
            "Your function returns the opposite of the reference on every input where both give True or False "
            "(%d of %d). Check what your final return statement actually tests." % (len(both), tried)
        )
    elif failing == tried and tried >= 5:
        out.append(
            "They disagree on every input I tried, so this is not an edge case: something basic is different."
        )
    mine = [x for x, _ in both]
    theirs = {y for _, y in both}
    if len(mine) >= 5 and len(set(mine)) == 1 and len(theirs) >= 2:
        out.append("Your function returned %s on every input I tried, while the reference's result depends on the input." % _clip(mine[0]))
    errors = [_raised(a) for a, _ in pairs]
    kinds = {e for e in errors if e}
    if kinds:
        common = max(kinds, key=errors.count)
        n_raise = errors.count(common)
        ref_raise = sum(1 for _, b in pairs if _raised(b))
        if n_raise >= 3 and n_raise > ref_raise:
            out.append("Your function raises %s on %d of the %d inputs I tried; the reference does so on %d." % (common, n_raise, tried, ref_raise))
    return out


def _clip(text: str, limit: int = 30) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


@dataclass
class Probe:
    """What testing many inputs revealed."""

    tried: int
    failing: int
    minimal: Optional[tuple] = None
    minimal_candidate: Optional[Trace] = None
    minimal_reference: Optional[Trace] = None
    patterns: List[str] = field(default_factory=list)
    passing: List[tuple] = field(default_factory=list)


def run_probe(candidate, reference, args, kwargs, names, first_failed, ta, tb, tolerance=None) -> Probe:
    """Try variations of ``args``, shrink a failing one, and look for a pattern."""
    rows = [(args, first_failed)]
    pairs = [(ta, tb)]
    failing_runs: Dict[str, tuple] = {repr(args): (args, ta, tb)} if first_failed else {}
    for v in _variants(args):
        t1, t2, bad = run_pair(candidate, reference, v, kwargs, tolerance)
        rows.append((v, bad))
        pairs.append((t1, t2))
        if bad:
            failing_runs[repr(v)] = (v, t1, t2)
    probe = Probe(tried=len(rows), failing=sum(1 for _, bad in rows if bad))
    if not failing_runs:
        return probe
    systematic = find_systematic(pairs, probe.failing)
    start = args if first_failed else min((r[0] for r in failing_runs.values()), key=lambda a: len(repr(a)))
    _, t1, t2 = failing_runs[repr(start)]
    probe.minimal, probe.minimal_candidate, probe.minimal_reference = _shrink(
        candidate, reference, start, kwargs, t1, t2, tolerance
    )
    probe.patterns = systematic + find_patterns(rows, names)
    probe.passing = sorted((a for a, bad in rows if not bad), key=lambda a: len(repr(a)))[:2]
    return probe
