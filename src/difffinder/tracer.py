"""Record how the variables of one function call change, line by line."""

from __future__ import annotations

import inspect
import os
import re
import sys
import sysconfig
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

RETURN = "<return>"  # pseudo-variable holding the value a call returned
RAISE = "<raise>"  # pseudo-variable holding the exception a call raised
MAX_REPR = 1000
_ADDRESS = re.compile(r"0x[0-9a-fA-F]+")
_MISSING = object()


class StepLimitExceeded(BaseException):
    """Raised inside a traced call that runs more than ``max_steps`` lines.

    It derives from BaseException so a student's ``except Exception`` cannot hide it.
    """


@dataclass(frozen=True)
class Event:
    """One variable taking a new value."""

    step: int  # how many lines had run when this happened
    var: str
    value: str  # repr() of the new value
    filename: str
    lineno: int  # the line that caused the change
    func: str
    depth: int  # 0 = the traced function itself, 1 = something it called, ...


@dataclass
class Trace:
    """Everything recorded from one call."""

    name: str
    events: List[Event] = field(default_factory=list)
    steps: int = 0
    truncated: bool = False
    arg_names: Dict[str, str] = field(default_factory=dict)  # "<arg0>" -> parameter name

    def history(self, var: str) -> List[Event]:
        """All the values ``var`` took, in order."""
        return [e for e in self.events if e.var == var]

    @property
    def variables(self) -> Set[str]:
        return {e.var for e in self.events if not e.var.startswith("<")}


def _prefixes():
    paths = {sysconfig.get_path(k) for k in ("stdlib", "platstdlib", "purelib", "platlib")}
    paths.add(os.path.dirname(os.path.abspath(__file__)))
    return tuple(os.path.normcase(os.path.abspath(p)) + os.sep for p in paths if p)


_PREFIXES = _prefixes()
_CACHE: Dict[str, bool] = {}


def _is_user_code(filename: str) -> bool:
    """True for notebook cells and scripts, False for the stdlib and installed packages."""
    hit = _CACHE.get(filename)
    if hit is None:
        if filename.startswith("<frozen"):
            hit = False
        elif filename.startswith("<"):
            hit = True  # <ipython-input-...>, <string>
        else:
            hit = not (os.path.normcase(os.path.abspath(filename)) + os.sep).startswith(_PREFIXES)
        _CACHE[filename] = hit
    return hit


def _safe_repr(value: Any) -> str:
    try:
        text = repr(value)
    except Exception:  # a broken __repr__ must not break the trace
        text = "<unrepresentable %s>" % type(value).__name__
    text = _ADDRESS.sub("0x...", text)  # object addresses differ between runs
    return text if len(text) <= MAX_REPR else text[:MAX_REPR] + "..."


def record(
    func: Callable[..., Any],
    args: tuple = (),
    kwargs: Optional[dict] = None,
    *,
    max_steps: int = 100_000,
) -> Trace:
    """Call ``func(*args, **kwargs)`` and record every change to its variables.

    Only your own code is traced: the standard library and installed packages are skipped.
    The call's return value (or exception) is stored under :data:`RETURN` / :data:`RAISE`.
    """
    kwargs = dict(kwargs or {})
    trace = Trace(name=getattr(func, "__qualname__", repr(func)))
    events = trace.events
    root = getattr(func, "__code__", None)
    active = [0]  # number of traced frames currently running
    counter = [0]  # lines executed so far
    last_root_line = [None]  # (filename, lineno, funcname) of the last line run at depth 0

    def flush(frame, seen, depth, lineno):
        code = frame.f_code
        changed = []
        for name, value in frame.f_locals.items():
            if name in code.co_freevars:  # a variable of the enclosing function, not this frame's own
                continue
            if name.startswith("__") or inspect.isroutine(value) or inspect.isclass(value) or inspect.ismodule(value):
                continue
            text = _safe_repr(value)
            if seen.get(name, _MISSING) != text:
                seen[name] = text
                changed.append((name, text))
        for name, text in sorted(changed):  # sorted: order inside one line must not matter
            events.append(Event(counter[0], name, text, code.co_filename, lineno, code.co_name, depth))

    def global_trace(frame, event, arg):
        if event != "call":
            return None
        code = frame.f_code
        if code is not root and not _is_user_code(code.co_filename):
            return None
        depth = active[0]
        active[0] += 1
        seen: Dict[str, str] = {}
        current = [code.co_firstlineno]

        def local_trace(frame, event, arg):
            if event == "line":
                counter[0] += 1
                if counter[0] > max_steps:
                    raise StepLimitExceeded()
                # State is "before this line runs", so changes belong to the previous line.
                flush(frame, seen, depth, current[0])
                current[0] = frame.f_lineno
                if depth == 0:
                    last_root_line[0] = (code.co_filename, current[0], code.co_name)
            elif event == "return":
                flush(frame, seen, depth, current[0])
                active[0] -= 1
            return local_trace

        return local_trace

    def add_end(var: str, text: str) -> None:
        where = last_root_line[0] or (
            getattr(root, "co_filename", "<unknown>"),
            getattr(root, "co_firstlineno", 0),
            trace.name,
        )
        events.append(Event(counter[0], var, text, where[0], where[1], where[2], 0))

    def add_arg_events() -> None:
        """Record the final state of each argument, so in-place changes are compared too."""
        try:
            bound = inspect.signature(func).bind(*args, **kwargs)
            bound.apply_defaults()
        except (TypeError, ValueError):
            return
        for idx, (name, value) in enumerate(bound.arguments.items()):
            var = "<arg%d>" % idx
            trace.arg_names[var] = name
            add_end(var, _safe_repr(value))

    previous = sys.gettrace()
    sys.settrace(global_trace)
    try:
        result = func(*args, **kwargs)
    except StepLimitExceeded:
        trace.truncated = True
    except Exception as exc:
        sys.settrace(previous)
        add_arg_events()
        add_end(RAISE, "%s: %s" % (type(exc).__name__, exc))
    else:
        sys.settrace(previous)
        add_arg_events()
        add_end(RETURN, _safe_repr(result))
    finally:
        sys.settrace(previous)
    trace.steps = counter[0]
    return trace
