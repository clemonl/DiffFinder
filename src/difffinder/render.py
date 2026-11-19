"""Turn a Comparison into plain text or notebook HTML."""

from __future__ import annotations

import html
import linecache

from .tracer import RAISE, RETURN, _safe_repr


def _short(text: str, limit: int = 60) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _names(cmp, n: int):
    return [cmp.candidate.arg_names.get("<arg%d>" % i) or "arg%d" % i for i in range(n)]


def _call(cmp, args: tuple) -> str:
    return ", ".join("%s=%s" % (n, _short(repr(a), 40)) for n, a in zip(_names(cmp, len(args)), args))


def _describe(trace, args: tuple) -> str:
    """What a call visibly did, in a few words."""
    parts = []
    raised, returned = trace.history(RAISE), trace.history(RETURN)
    if raised:
        parts.append("raises " + _short(raised[-1].value, 50))
    elif returned:
        parts.append("returns " + _short(returned[-1].value, 50))
    elif trace.truncated:
        parts.append("never finishes (stopped after %d steps)" % trace.steps)
    for ev in trace.events:
        if ev.var.startswith("<arg"):
            idx = int(ev.var[4:-1])
            if idx < len(args) and ev.value != _safe_repr(args[idx]):
                parts.append("changes `%s` to %s" % (trace.arg_names.get(ev.var, ev.var), _short(ev.value, 50)))
    return ", ".join(parts) or "does nothing visible"


def _where(ev) -> str:
    src = linecache.getline(ev.filename, ev.lineno).strip()
    return "line %d in %s()%s" % (ev.lineno, ev.func, (": " + src) if src else "")


def _label(cmp, var: str) -> str:
    if var == RETURN:
        return "the return value"
    if var == RAISE:
        return "how the call ended"
    if var.startswith("<arg"):
        return "the final state of argument '%s'" % (cmp.candidate.arg_names.get(var) or var)
    return "variable '%s'" % var


def _header(cmp) -> str:
    p, d = cmp.probe, cmp.divergence
    if cmp.outcomes_differ and p is not None and p.failing:
        return "DIFFERENT: yours disagrees with the reference on %d of the %d inputs I tried (including yours)." % (p.failing, p.tried)
    if cmp.outcomes_differ:
        return "DIFFERENT: the two functions give different results on your input."
    if p is not None and p.failing:
        return "DIFFERENT: they agree on your input, but disagree on %d of %d other inputs I tried." % (p.failing, p.tried - 1)
    if d is not None:
        return "DIFFERENT: the runs first diverge on %s (change #%d)." % (_label(cmp, d.var), d.position + 1)
    return "DIFFERENT."


def _off_track(cmp) -> str:
    """One sentence on the first step where the candidate's run leaves the reference's."""
    d = cmp.divergence
    if d is None or d.var.startswith("<"):
        return ""
    c, r = d.candidate, d.reference
    if c is not None:
        src = linecache.getline(c.filename, c.lineno).strip()
        tail = " (the reference has %s at that point)" % _short(r.value) if r is not None else " (the reference never changes it)"
        return "Where your run goes off track: line %d%s sets %s = %s%s." % (
            c.lineno, (" (`%s`)" % src) if src else "", d.var, _short(c.value), tail,
        )
    return "Where it goes off track: the reference reaches %s = %s (%s), but your run never does." % (d.var, _short(r.value), _where(r))


def _skipped_note(cmp) -> str:
    return "not compared step by step: %s (same name, but the runs barely agree on it, so it probably means different things; pass watch=[...] to force it)" % ", ".join(cmp.skipped)


def _blocks(cmp):
    """The factual parts, shared by the text and HTML views: (label, call, yours, reference) rows."""
    rows, p = [], cmp.probe
    if cmp.outcomes_differ:
        rows.append(("Your input", _call(cmp, cmp.args), _describe(cmp.candidate, cmp.args), _describe(cmp.reference, cmp.args)))
    if p is not None and p.minimal is not None and (p.minimal != cmp.args or not cmp.outcomes_differ):
        rows.append((
            "Smallest failing input I found", _call(cmp, p.minimal),
            _describe(p.minimal_candidate, p.minimal), _describe(p.minimal_reference, p.minimal),
        ))
    return rows


def to_text(cmp, include_ai: bool = True) -> str:
    p = cmp.probe
    if cmp.same:
        text = "SAME behaviour: %s and %s give the same result" % (cmp.candidate.name, cmp.reference.name)
        if p is not None and p.tried > 1:
            text += ", also on %d other inputs I tried" % (p.tried - 1)
        text += "."
        return text + ("\n  note: " + _skipped_note(cmp) if cmp.skipped else "")
    lines = [_header(cmp)]
    for label, call, yours, ref in _blocks(cmp):
        lines += ["", "%s (%s):" % (label, call), "  yours     : " + yours, "  reference : " + ref]
    extra = list(p.patterns) if p is not None else []
    if p is not None and p.failing and p.passing:
        extra.append("It does agree on: " + "; ".join(_call(cmp, a) for a in p.passing) + ".")
    if extra:
        lines += [""] + extra
    off = _off_track(cmp)
    if off:
        lines += ["", off]
    if cmp.hints:
        lines += ["", "Hints:"] + ["  - " + h for h in cmp.hints[:3]]
    if cmp.skipped:
        lines += ["", "note: " + _skipped_note(cmp)]
    if include_ai and cmp.ai_hint:
        lines += ["", "AI hint:"] + ["  " + part for part in cmp.ai_hint.splitlines() if part.strip()]
    elif include_ai and cmp.ai_error:
        lines += ["", "AI hint unavailable: " + _short(cmp.ai_error.replace("\n", " "), 200)]
    for who, tr in (("candidate", cmp.candidate), ("reference", cmp.reference)):
        if tr.truncated:
            lines.append("note: the %s run was stopped after %d steps." % (who, tr.steps))
    return "\n".join(lines)


def to_html(cmp) -> str:
    e = html.escape
    if cmp.same:
        return "<p><b>SAME behaviour</b>: both give the same result.</p>"
    p = cmp.probe
    out = ["<p><b>%s</b></p>" % e(_header(cmp))]
    rows = _blocks(cmp)
    if rows:
        body = "".join(
            "<tr><th style='text-align:left'>%s</th><td><code>%s</code></td><td>yours: %s</td><td>reference: %s</td></tr>"
            % (e(label), e(call), e(yours), e(ref))
            for label, call, yours, ref in rows
        )
        out.append("<table>%s</table>" % body)
    extra = list(p.patterns) if p is not None else []
    if p is not None and p.failing and p.passing:
        extra.append("It does agree on: " + "; ".join(_call(cmp, a) for a in p.passing) + ".")
    out += ["<p>%s</p>" % e(x) for x in extra]
    off = _off_track(cmp)
    if off:
        out.append("<p>%s</p>" % e(off))
    if cmp.hints:
        out.append("<p><b>Hints</b></p><ul>%s</ul>" % "".join("<li>%s</li>" % e(h) for h in cmp.hints[:3]))
    if cmp.ai_hint:
        out.append("<p><b>AI hint</b></p><p>%s</p>" % e(cmp.ai_hint).replace("\n", "<br>"))
    elif cmp.ai_error:
        out.append("<p><i>AI hint unavailable: %s</i></p>" % e(_short(cmp.ai_error, 200)))
    return "".join(out)
