"""Run a function once and record what it visibly did."""

from __future__ import annotations

import copy
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional


def short(text: str, limit: int = 60) -> str:
    """Shorten long text for display."""
    return text if len(text) <= limit else text[: limit - 3] + "..."


@dataclass
class Outcome:
    """What one call did: its result or exception, and the final state of its arguments."""

    returned: Any = None
    error_type: Optional[str] = None  # for example "ValueError"; None if the call returned normally
    error_message: str = ""
    inputs: Dict[str, str] = field(default_factory=dict)  # argument name -> repr before the call
    arguments: Dict[str, Any] = field(default_factory=dict)  # argument name -> object after the call

    @property
    def raised(self) -> bool:
        return self.error_type is not None

    def describe(self) -> str:
        """The result in a few words, for example ``returned 6`` or ``raised ValueError: ...``."""
        if self.raised:
            detail = (": " + self.error_message) if self.error_message else ""
            return "raised %s%s" % (self.error_type, detail)
        return "returned %s" % short(repr(self.returned))


def _bind(func: Callable[..., Any], args: tuple, kwargs: dict) -> Dict[str, Any]:
    """Map parameter names to the objects passed in (the objects are shared, not copied)."""
    try:
        return dict(inspect.signature(func).bind(*args, **kwargs).arguments)
    except (TypeError, ValueError):  # no signature available, or the arguments do not fit it
        named = {"arg%d" % i: a for i, a in enumerate(args)}
        named.update(kwargs)
        return named


def run(func: Callable[..., Any], args: tuple = (), kwargs: Optional[dict] = None) -> Outcome:
    """Call ``func(*args, **kwargs)`` on a deep copy of the arguments and record what happened.

    An exception is recorded, not raised. Because the call works on copies, your own data is never changed,
    but changes the function makes to its arguments are captured in ``Outcome.arguments``.
    """
    args = copy.deepcopy(tuple(args))
    kwargs = copy.deepcopy(dict(kwargs or {}))
    arguments = _bind(func, args, kwargs)
    inputs = {name: short(repr(value), 500) for name, value in arguments.items()}
    try:
        outcome = Outcome(returned=func(*args, **kwargs))
    except Exception as exc:
        outcome = Outcome(error_type=type(exc).__name__, error_message=str(exc))
    outcome.inputs, outcome.arguments = inputs, arguments
    return outcome
