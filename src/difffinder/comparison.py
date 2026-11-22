"""Compare two functions on the same input."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

from .outcome import Outcome, run, short
from .values import same_value, validate_tolerance


@dataclass
class Difference:
    """One way the two functions behave differently."""

    what: str  # "result" or "argument 'nums' afterwards"
    yours: str
    reference: str


@dataclass(repr=False)
class Comparison:
    """The result of :func:`compare`."""

    candidate_name: str
    reference_name: str
    candidate: Outcome
    reference: Outcome
    differences: List[Difference] = field(default_factory=list)

    @property
    def same(self) -> bool:
        """True if the two functions did the same thing on this input."""
        return not self.differences

    def __str__(self) -> str:
        call = ", ".join("%s=%s" % (name, short(value, 40)) for name, value in self.candidate.inputs.items())
        names = "%s and %s" % (self.candidate_name, self.reference_name)
        if self.same:
            return "SAME: %s behave the same on (%s)." % (names, call)
        lines = ["DIFFERENT: %s behave differently on (%s)." % (names, call)]
        for d in self.differences:
            lines.append("  %s: yours %s, the reference %s." % (d.what, d.yours, d.reference))
        return "\n".join(lines)

    __repr__ = __str__  # so a Comparison displays as text when it is the last line of a notebook cell


def _differences(mine: Outcome, ref: Outcome, tolerance: Optional[float] = None) -> List[Difference]:
    found: List[Difference] = []
    if mine.raised or ref.raised:
        if mine.error_type != ref.error_type:  # same exception type counts as the same
            found.append(Difference("result", mine.describe(), ref.describe()))
    elif not same_value(mine.returned, ref.returned, tolerance):
        found.append(Difference("result", mine.describe(), ref.describe()))
    # Arguments are matched by position, so the two functions may name their parameters differently.
    for (name, a), (_, b) in zip(mine.arguments.items(), ref.arguments.items()):
        if not same_value(a, b, tolerance):
            found.append(Difference("argument '%s' afterwards" % name, short(repr(a)), short(repr(b))))
    return found


def _name(func: Callable[..., Any]) -> str:
    return getattr(func, "__name__", None) or repr(func)


def compare(
    candidate: Callable[..., Any],
    reference: Callable[..., Any],
    args: tuple = (),
    kwargs: Optional[dict] = None,
    tolerance: Optional[float] = None,
) -> Comparison:
    """Run both functions on the same input and report whether they behave the same.

    ``candidate`` is usually your own (possibly buggy) function and ``reference`` a known-good one.
    "Behave the same" means: the same return value, the same kind of exception, and the same changes
    to the arguments. How the functions are written inside does not matter. If ``tolerance`` is given,
    corresponding numerical values may differ by up to that absolute amount.
    """
    validate_tolerance(tolerance)
    mine = run(candidate, args, kwargs)
    ref = run(reference, args, kwargs)
    return Comparison(_name(candidate), _name(reference), mine, ref, _differences(mine, ref, tolerance))
