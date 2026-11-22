"""Compare two functions: where do they differ, on which inputs, and why."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

from .probe import outcome
from .tracer import RAISE, Event, Trace, record
from .values import same_repr, validate_tolerance


def _special(name: str) -> bool:
    """<return>, <raise> and <argN> are outcome pseudo-variables, not real variables."""
    return name.startswith("<")


@dataclass
class Divergence:
    """The first place two runs disagree, step by step."""

    var: str  # the variable (or <return> / <raise> / <argN>) that disagrees
    position: int  # 0-based: it is that variable's n-th new value
    candidate: Optional[Event]  # None means the candidate never made this change
    reference: Optional[Event]
    agreed: List[str]  # the last few values both runs agreed on


@dataclass(repr=False)
class TraceComparison:
    candidate: Trace
    reference: Trace
    divergence: Optional[Divergence]
    compared: List[str]  # variable names that were compared step by step
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    skipped: List[str] = field(default_factory=list)  # same name, but probably a different meaning
    hints: List[str] = field(default_factory=list)  # plain-English clues, generated offline
    candidate_fn: Any = None
    reference_fn: Any = None
    ai_hint: Optional[str] = None  # filled in when compare_traces(..., ai=...) succeeds
    ai_error: Optional[str] = None  # why the AI hint is missing, if it failed
    outcomes_differ: bool = False  # on the input you gave: different result, exception or side effect
    strict: bool = False  # watch=/rename= given: step-by-step differences count too
    probe: Any = None  # difffinder.probe.Probe: what testing many other inputs showed

    @property
    def same(self) -> bool:
        if self.probe is not None and self.probe.failing:
            return False
        return self.divergence is None if self.strict else not self.outcomes_differ

    def explain(self, llm: Any = None, share_reference: bool = True) -> str:
        """Ask an LLM for a short hint. See :mod:`difffinder.ai`."""
        from .ai import explain

        return explain(self, llm, share_reference)

    def __str__(self) -> str:
        from .render import to_text

        return to_text(self)

    __repr__ = __str__

    def _repr_html_(self) -> str:
        from .render import to_html

        return to_html(self)


def find_divergence(
    candidate: Trace,
    reference: Trace,
    *,
    watch: Optional[Iterable[str]] = None,
    rename: Optional[Dict[str, str]] = None,
    tolerance: Optional[float] = None,
):
    """Return ``(divergence_or_None, compared_names, skipped_names)`` for two traces.

    Each shared variable's history is compared separately, so unrelated assignments in a different order
    are not a difference. The outcome (return value, exception, final state of every argument) is always
    compared. In automatic mode (no ``watch``/``rename``) a variable the two runs barely agree on is
    *skipped*: different algorithms often reuse a name like ``i`` for different things.
    """
    rename = rename or {}

    def histories(trace: Trace, mapping: Dict[str, str]) -> Dict[str, List[Event]]:
        out: Dict[str, List[Event]] = {}
        for e in trace.events:
            out.setdefault(mapping.get(e.var, e.var), []).append(e)
        return out

    ha, hb = histories(candidate, rename), histories(reference, {})
    auto = watch is None and not rename
    specials = {n for n in set(ha) | set(hb) if _special(n)}
    names = (set(watch) if watch is not None else set(ha) & set(hb)) | specials

    found = []
    for name in names:
        a, b = ha.get(name, []), hb.get(name, [])
        for i in range(max(len(a), len(b))):
            ea = a[i] if i < len(a) else None
            eb = b[i] if i < len(b) else None
            if ea is None or eb is None or not same_repr(ea.value, eb.value, tolerance):
                when = ea.step if ea is not None else candidate.steps
                if _special(name):
                    rank = 1 if name == RAISE else 2
                elif ea is None and RAISE in ha:
                    rank = 1.5  # "never got here" is a consequence of the crash, so the crash goes first
                else:
                    rank = 0  # real variables beat outcomes
                agreed = [e.value for e in a[max(0, i - 3) : i]]
                found.append(((when, rank, name), Divergence(name, i, ea, eb, agreed)))
                break
    found.sort(key=lambda item: item[0])

    # A name is only trusted to mean the same thing in both functions if it is a parameter of both,
    # or the two runs agreed on at least two of its values before diverging.
    params = set(candidate.arg_names.values()) & set(reference.arg_names.values())
    chosen, skipped = None, []
    for _, div in found:
        aligned = len(div.agreed) >= 2 or (div.var in params and div.position >= 1)
        if auto and not _special(div.var) and not aligned:
            skipped.append(div.var)
            continue
        chosen = div
        break
    compared = sorted(n for n in names if not _special(n) and (n in ha or n in hb))
    return chosen, compared, skipped


def compare_traces(
    candidate: Callable[..., Any],
    reference: Callable[..., Any],
    args: tuple = (),
    kwargs: Optional[dict] = None,
    *,
    watch: Optional[Iterable[str]] = None,
    rename: Optional[Dict[str, str]] = None,
    max_steps: int = 100_000,
    probe: bool = True,
    ai: Any = None,
    tolerance: Optional[float] = None,
) -> TraceComparison:
    """Run both functions on the same input and report how they differ.

    ``candidate`` is usually the buggy or student version, ``reference`` the known-good one. Each run gets
    its own deep copy of ``args``/``kwargs``, so in-place changes cannot leak.

    The verdict is based on what each function visibly does (return value, exception, changes to its
    arguments), so it works however differently the two are written. With ``probe=True`` (the default) it
    also tries many variations of your input, shrinks a failing one to the smallest case, and describes
    when they disagree. This calls both functions many times, so use ``probe=False`` for functions with
    side effects or that are slow.

    ``watch`` limits the step-by-step comparison to the named variables (``watch=[]`` compares only the
    outcome). ``rename`` maps variable names in ``candidate`` to the names in ``reference``. Giving either
    means you vouch that the names line up, and step-by-step differences then count as differences.
    ``tolerance`` allows corresponding numerical values to differ by up to the given absolute amount.

    ``ai=True`` adds a short model-written hint (needs an API key, see :mod:`difffinder.ai`); ``ai`` may
    also be ``"hermes"``, ``"openai"`` or a function ``prompt -> str``. If the model cannot be reached the
    comparison still works and the reason is shown instead.
    """
    validate_tolerance(tolerance)
    kwargs = kwargs or {}
    ta = record(candidate, copy.deepcopy(args), copy.deepcopy(kwargs), max_steps=max_steps)
    tb = record(reference, copy.deepcopy(args), copy.deepcopy(kwargs), max_steps=max_steps)
    divergence, compared, skipped = find_divergence(
        ta, tb, watch=watch, rename=rename, tolerance=tolerance
    )
    strict = watch is not None or bool(rename)
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
    if not strict and not differ:
        divergence = None  # internal steps may differ between two correct solutions
    result = TraceComparison(
        ta, tb, divergence, compared, tuple(args), dict(kwargs), skipped, [], candidate, reference,
        outcomes_differ=differ, strict=strict,
    )
    if probe and args:
        from .probe import run_probe

        names = [ta.arg_names.get("<arg%d>" % i, "arg%d" % i) for i in range(len(args))]
        try:
            result.probe = run_probe(
                candidate, reference, tuple(args), kwargs, names, differ, ta, tb, tolerance=tolerance
            )
        except Exception:  # probing is a bonus; never let it break the comparison
            result.probe = None
    if not result.same:
        from .hints import generate

        result.hints = generate(result)
        if ai:
            from .ai import explain

            try:
                result.ai_hint = explain(result, "auto" if ai is True else ai)
            except Exception as exc:  # a missing key or offline model must never break the comparison
                result.ai_error = "%s: %s" % (type(exc).__name__, exc)
    return result


def find_difference(
    candidate: Callable[..., Any],
    reference: Callable[..., Any],
    cases: Iterable[Any],
    **options: Any,
) -> Optional[TraceComparison]:
    """Try each input in ``cases``; return the first :class:`TraceComparison` that differs, or None.

    A case that is a tuple is used as the positional arguments; anything else is wrapped.
    """
    options.setdefault("probe", False)  # this function is itself the search
    for case in cases:
        args = case if isinstance(case, tuple) else (case,)
        result = compare_traces(candidate, reference, args, **options)
        if not result.same:
            return result
    return None
