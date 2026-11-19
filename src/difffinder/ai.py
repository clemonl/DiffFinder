"""Optional: ask a language model for a short hint. Off unless you ask for it.

Quickest way: set an API key, then pass ``ai=True``::

    import os, getpass
    os.environ["DEEPSEEK_API_KEY"] = getpass.getpass()   # or OPENAI_API_KEY
    compare_traces(mine, reference, args=(...), ai=True)

Ready-made models: :func:`openai_compatible` (any OpenAI-style endpoint, standard library only) and
:func:`hermes_llm` (the Hermes Agent via ``hermes-acp-sdk``). Or pass any function ``llm(prompt) -> str``.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import tempfile
import threading
import urllib.request
from typing import Callable, Optional

SYSTEM = (
    "You are a friendly programming tutor talking to one first-year student. You are given the results of "
    "automatically testing their function against a correct reference function: the inputs where the two "
    "differ, the smallest failing input, a pattern for when it fails, and what each function did. "
    "Reply in at most 5 short sentences, in plain spoken English, not as a report, and without repeating "
    "numbers the student can already see. Say what their code most likely gets wrong, pointing at one "
    "specific line or variable, then ask ONE guiding question. "
    "Do not write corrected code and do not reveal the reference solution (do not quote or describe it). "
    "No praise, no apologies."
)

_KEY_VARS = ("DIFFFINDER_API_KEY", "SOCRATIC_LLM_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY")


def _source(fn) -> str:
    try:
        return inspect.getsource(fn)
    except (OSError, TypeError):
        return "(source not available)"


def _short(text: str, limit: int = 80) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def build_prompt(cmp, share_reference: bool = True) -> str:
    """The text sent to the model: the code, the evidence, and what the student's run actually did."""
    from .render import to_text

    d = cmp.divergence
    parts = ["INPUT: %r" % (cmp.args,), "STUDENT'S FUNCTION:\n" + _source(cmp.candidate_fn)]
    if share_reference:
        parts.append("REFERENCE FUNCTION (for your eyes only, never quote or describe it):\n" + _source(cmp.reference_fn))
    parts.append("AUTOMATIC COMPARISON:\n" + to_text(cmp, include_ai=False))
    if d is not None:
        def values(trace):
            vals = [_short(e.value, 40) for e in trace.history(d.var)][:15]
            return ", ".join(vals) if vals else "(never set)"

        parts.append(
            "VALUES OF '%s' IN ORDER:\n  student  : %s\n  reference: %s" % (d.var, values(cmp.candidate), values(cmp.reference))
        )
    probe = cmp.probe
    focus = probe.minimal_candidate if probe is not None and probe.minimal_candidate is not None else cmp.candidate
    recent = [e for e in focus.events if not e.var.startswith("<")][-12:]
    if recent:
        parts.append(
            "LAST CHANGES IN THE STUDENT'S RUN%s:\n" % (" (on the smallest failing input)" if focus is not cmp.candidate else "")
            + "\n".join("  line %d: %s = %s" % (e.lineno, e.var, _short(e.value, 60)) for e in recent)
        )
    return "\n\n".join(parts)


def openai_compatible(
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    timeout: float = 60.0,
) -> Callable[[str], str]:
    """Return ``llm(prompt) -> str`` for an OpenAI-style chat endpoint.

    Everything can come from the environment. Key: DIFFFINDER_API_KEY, SOCRATIC_LLM_API_KEY, DEEPSEEK_API_KEY
    or OPENAI_API_KEY (first one found). With a DeepSeek key, the DeepSeek endpoint and ``deepseek-chat`` are
    used by default. Override with DIFFFINDER_BASE_URL / DIFFFINDER_MODEL (``SOCRATIC_LLM_*`` and
    ``OPENAI_BASE_URL`` / ``OPENAI_MODEL`` are read too).
    """
    env = os.environ.get
    own_key = next((env(v) for v in _KEY_VARS[:3] if env(v)), None)
    openai_key = env("OPENAI_API_KEY")
    key = api_key if api_key is not None else (own_key or openai_key or "")
    use_openai = api_key is None and not own_key and bool(openai_key)
    base = (
        base_url
        or env("DIFFFINDER_BASE_URL")
        or env("SOCRATIC_LLM_BASE_URL")
        or env("OPENAI_BASE_URL")
        or ("https://api.openai.com/v1" if use_openai else "https://api.deepseek.com")
    )
    model = model or env("DIFFFINDER_MODEL") or env("SOCRATIC_LLM_MODEL") or env("OPENAI_MODEL") or (None if use_openai else "deepseek-chat")
    if not key and not (base_url or env("DIFFFINDER_BASE_URL")):
        raise RuntimeError(
            "No API key found. Set DEEPSEEK_API_KEY (or OPENAI_API_KEY) first, for example:\n"
            "    import os, getpass; os.environ['DEEPSEEK_API_KEY'] = getpass.getpass()"
        )
    if not model:
        raise RuntimeError("Set DIFFFINDER_MODEL to the model name you want to use (for example your OpenAI model).")
    url = base.rstrip("/") + "/chat/completions"

    def ask(prompt: str) -> str:
        body = json.dumps(
            {
                "model": model,
                "temperature": 0.2,
                "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            }
        ).encode()
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + key}
        with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=timeout) as r:
            return json.load(r)["choices"][0]["message"]["content"].strip()

    ask.url, ask.model = url, model  # handy when debugging which endpoint is used
    return ask


def _run(make_coro):
    """Run a coroutine from sync code, also when a loop is already running (Jupyter)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(make_coro())
    box = {}

    def worker():
        try:
            box["value"] = asyncio.run(make_coro())
        except BaseException as exc:  # re-raised in the caller's thread
            box["error"] = exc

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box["value"]


def hermes_llm(timeout: float = 120.0, **client_kwargs) -> Callable[[str], str]:
    """Return ``llm(prompt) -> str`` that asks the Hermes Agent through ``hermes-acp-sdk``.

    Needs ``pip install hermes-acp-sdk "hermes-agent[acp]"`` (Hermes requires Python 3.11 to 3.13) and a
    provider already configured for Hermes. Hermes has its own file and terminal tools that the SDK cannot
    sandbox, so by default it is started in an **empty temporary folder**. Extra keyword arguments
    (``profile=...``, ``clone_provider=True``, ...) go to ``HermesClient``.
    """
    try:
        import hermes_acp_sdk  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            'hermes_llm needs the Hermes SDK: pip install hermes-acp-sdk "hermes-agent[acp]" '
            "(Hermes requires Python 3.11 to 3.13). Or set DEEPSEEK_API_KEY / OPENAI_API_KEY to use an online model."
        ) from exc

    async def ask_async(prompt: str) -> str:
        from hermes_acp_sdk import AgentText, HermesClient

        with tempfile.TemporaryDirectory(prefix="difffinder-") as empty:
            kwargs = dict(client_kwargs)
            kwargs.setdefault("cwd", empty)
            parts = []

            async def turn():
                async with HermesClient(**kwargs) as hermes:
                    async with hermes.session() as session:
                        async for event in session.prompt(SYSTEM + "\n\n" + prompt):
                            if isinstance(event, AgentText):
                                parts.append(event.text)

            await asyncio.wait_for(turn(), timeout)
            return "".join(parts).strip()

    return lambda prompt: _run(lambda: ask_async(prompt))


def _resolve(llm):
    if callable(llm):
        return llm
    if llm == "hermes":
        return hermes_llm()
    if llm == "openai":
        return openai_compatible()
    if llm in (None, "auto"):
        configured = any(os.environ.get(v) for v in _KEY_VARS) or os.environ.get("DIFFFINDER_BASE_URL")
        return openai_compatible() if configured else hermes_llm()
    raise ValueError("llm must be a function, 'hermes', 'openai' or 'auto'")


def explain(cmp, llm=None, share_reference: bool = True) -> str:
    """Return a short model hint for a :class:`~difffinder.TraceComparison`.

    ``llm`` is a function ``prompt -> str``, or ``"hermes"`` / ``"openai"`` / ``"auto"`` (the default: an
    online model if an API key is set, otherwise Hermes). With ``share_reference=False`` the reference
    function's source is not sent, which hides the solution but gives the model less to work with.
    """
    if cmp.same:
        return "Nothing to explain: the two functions behave the same."
    return _resolve(llm)(build_prompt(cmp, share_reference))
