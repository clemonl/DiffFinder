import json
import os

from difffinder import RAISE, RETURN, compare_traces, find_difference, record


def sum_ok(n):
    total = 0
    for i in range(n + 1):
        total += i
    return total


def sum_off_by_one(n):
    total = 0
    for i in range(n):
        total += i
    return total


def mean_ok(xs):
    total = 0
    for x in xs:
        total += x
    return total / len(xs)


def mean_bad(xs):
    total = 0
    for x in xs:
        total += x
    return total / (len(xs) + 1)


def test_identical_functions_are_the_same():
    cmp = compare_traces(sum_ok, sum_ok, args=(5,))
    assert cmp.same and cmp.divergence is None
    assert "SAME" in str(cmp)


def test_off_by_one_loop_is_pinpointed_on_the_loop_variable():
    d = compare_traces(sum_off_by_one, sum_ok, args=(4,)).divergence
    assert d.var == "i" and d.position == 4
    assert d.candidate is None and d.reference.value == "4"


def test_wrong_return_value_is_reported_on_return():
    d = compare_traces(mean_bad, mean_ok, args=([1, 2, 3],)).divergence
    assert d.var == RETURN
    assert d.candidate.value == "1.5" and d.reference.value == "2.0"


def test_inputs_are_deep_copied_so_in_place_changes_are_visible_but_isolated():
    def sort_in_place(a):
        a.sort()
        return a

    def sorted_copy(a):
        return sorted(a)

    data = [3, 1, 2]
    cmp = compare_traces(sort_in_place, sorted_copy, args=(data,))
    assert data == [3, 1, 2]  # caller's list untouched
    assert cmp.divergence.var == "a"  # the candidate mutated its input


def test_rename_lines_up_different_variable_names():
    def f(n):
        acc = 0
        for k in range(n):
            acc += k
        return acc

    def g(n):
        total = 0
        for i in range(n):
            total += i
        return total

    assert "total" not in compare_traces(f, g, args=(4,)).compared
    renamed = compare_traces(f, g, args=(4,), rename={"acc": "total", "k": "i"})
    assert renamed.same and "total" in renamed.compared


def test_exception_versus_return():
    def first_bad(xs):
        return xs[0]

    def first_ok(xs):
        return xs[0] if xs else None

    d = compare_traces(first_bad, first_ok, args=([],)).divergence
    assert d.var == RAISE and "IndexError" in d.candidate.value and d.reference is None


def test_find_difference_returns_the_first_failing_input():
    def abs_bad(x):
        return x

    def abs_ok(x):
        return -x if x < 0 else x

    hit = find_difference(abs_bad, abs_ok, [1, 0, -3, 5])
    assert hit is not None and hit.args == (-3,)
    assert find_difference(abs_ok, abs_ok, [1, 0, -3]) is None


def test_step_limit_stops_infinite_loops():
    def forever():
        x = 0
        while True:
            x += 1

    trace = record(forever, max_steps=50)
    assert trace.truncated and trace.steps > 50


def test_library_code_is_not_traced():
    def uses_json(x):
        return json.dumps({"x": x})

    trace = record(uses_json, (1,))
    assert {os.path.basename(e.filename) for e in trace.events} == {"test_trace_comparison.py"}


def test_rendering():
    cmp = compare_traces(mean_bad, mean_ok, args=([1, 2, 3],))
    assert "DIFFERENT" in str(cmp) and "1.5" in str(cmp) and "2.0" in str(cmp)
    page = cmp._repr_html_()
    assert "<table" in page and "&lt;" not in "SAME"  # table rendered
    assert "SAME" in compare_traces(sum_ok, sum_ok, args=(3,))._repr_html_()


# ---- different algorithms, hints, optional AI ---------------------------------------------

def user_buggy(nums, lower_bound, upper_bound):
    num = nums
    lst = []
    for i in nums:
        for x in str(i):
            if int(x) % 2 != 0:
                sec = False
        else:
            sec = True
        if not (lower_bound <= i < upper_bound and sec):
            lst.append(i)
    for y in lst:
        nums = nums.remove(y)
    return nums == num


def user_reference(nums, lower_bound, upper_bound):
    def to_filter(x):
        return not (lower_bound <= x < upper_bound and all(int(d) % 2 == 0 for d in str(abs(x))))

    mutated = False
    for i in range(len(nums) - 1, -1, -1):
        if to_filter(nums[i]):
            nums.pop(i)
            mutated = True
    return mutated


def test_reused_variable_names_in_different_algorithms_are_not_noise():
    cmp = compare_traces(user_buggy, user_reference, args=([2, 4, 6], 0, 10))
    assert cmp.divergence.var == RETURN  # not 'x' or 'i'
    assert {"x", "i"} <= set(cmp.skipped)
    forced = compare_traces(user_buggy, user_reference, args=([2, 4, 6], 0, 10), watch=["i"])
    assert forced.divergence.var == "i"  # watch= forces the comparison


def test_list_that_becomes_none_is_pointed_out():
    cmp = compare_traces(user_buggy, user_reference, args=([12, 3, 40, 8], 5, 50))
    assert cmp.divergence.var == "nums" and cmp.divergence.candidate.value == "None"
    text = " ".join(cmp.hints)
    assert "returns None" in text or "return None" in text
    assert "else:" in text  # for-else without break
    assert "does not copy" in text  # num = nums


def test_exception_hint_for_negative_numbers():
    cmp = compare_traces(user_buggy, user_reference, args=([2, -4], 0, 10))
    assert cmp.divergence.var == RAISE
    assert any("Negative numbers" in h for h in cmp.hints)


def test_final_state_of_arguments_is_compared():
    def keeps(a):
        return len(a)

    def clears(a):
        n = len(a)
        a.clear()
        return n

    d = compare_traces(clears, keeps, args=([1, 2],)).divergence
    assert d.var == "<arg0>" or d.var == "a"  # mutated input is reported
    assert "a" in str(compare_traces(clears, keeps, args=([1, 2],)))


def test_ai_hook_sends_report_to_an_openai_style_server():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["auth"] = self.headers["Authorization"]
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            reply = json.dumps({"choices": [{"message": {"content": " Think about what remove returns. "}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        from difffinder import openai_compatible

        cmp = compare_traces(user_buggy, user_reference, args=([12, 3, 40, 8], 5, 50))
        llm = openai_compatible("http://127.0.0.1:%d/v1" % server.server_port, "secret", "test-model")
        assert cmp.explain(llm) == "Think about what remove returns."
    finally:
        server.shutdown()
    assert seen["auth"] == "Bearer secret" and seen["body"]["model"] == "test-model"
    prompt = seen["body"]["messages"][1]["content"]
    assert "DIFFERENT" in prompt and "def user_buggy" in prompt
    assert "do not reveal the reference" in seen["body"]["messages"][0]["content"].lower() or "reveal" in seen["body"]["messages"][0]["content"]


# ---- Hermes adapter (tested against a stand-in for hermes_acp_sdk) ------------------------------

def _fake_hermes(seen):
    import types

    mod = types.ModuleType("hermes_acp_sdk")

    class AgentText:
        def __init__(self, text):
            self.text = text

    class Finished:
        pass

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def prompt(self, text):
            seen["prompt"] = text
            yield AgentText("Think about ")
            yield AgentText("what remove returns.")
            yield Finished()

    class HermesClient:
        def __init__(self, **kw):
            seen["kw"] = kw
            seen["cwd_was_empty"] = os.listdir(kw["cwd"]) == []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def session(self):
            return Session()

    mod.AgentText, mod.Finished, mod.HermesClient = AgentText, Finished, HermesClient
    return mod


def test_hermes_adapter_streams_text_and_starts_in_an_empty_folder():
    import asyncio
    import sys

    from difffinder import hermes_llm

    seen = {}
    old = sys.modules.get("hermes_acp_sdk")
    sys.modules["hermes_acp_sdk"] = _fake_hermes(seen)
    try:
        cmp = compare_traces(user_buggy, user_reference, args=([12, 3, 40, 8], 5, 50))
        assert cmp.explain(hermes_llm(profile="difffinder")) == "Think about what remove returns."
        assert seen["cwd_was_empty"] and seen["kw"]["profile"] == "difffinder"
        assert "DIFFERENT" in seen["prompt"] and "Do not write corrected code" in seen["prompt"]

        async def inside_a_running_loop():  # what a Jupyter cell looks like
            return cmp.explain("hermes")

        assert asyncio.run(inside_a_running_loop()) == "Think about what remove returns."
    finally:
        if old is None:
            sys.modules.pop("hermes_acp_sdk", None)
        else:
            sys.modules["hermes_acp_sdk"] = old


def test_hermes_adapter_explains_how_to_install_when_missing():
    import sys

    from difffinder import hermes_llm

    old = sys.modules.pop("hermes_acp_sdk", None)
    try:
        try:
            hermes_llm()
        except RuntimeError as exc:
            assert "hermes-acp-sdk" in str(exc) and "3.11" in str(exc)
        else:
            assert False, "expected a RuntimeError"
    finally:
        if old is not None:
            sys.modules["hermes_acp_sdk"] = old


def test_selfcheck_passes_and_cleans_up():
    import linecache

    from difffinder import selfcheck

    assert selfcheck(verbose=False) is True
    assert "<ipython-input-1-difffinder>" not in linecache.cache


# ---- ai=True, environment keys, prompt content ---------------------------------------------

_AI_ENV = ("DIFFFINDER_API_KEY", "SOCRATIC_LLM_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY",
           "DIFFFINDER_BASE_URL", "SOCRATIC_LLM_BASE_URL", "OPENAI_BASE_URL",
           "DIFFFINDER_MODEL", "SOCRATIC_LLM_MODEL", "OPENAI_MODEL")


class _clean_ai_env:
    """Temporarily remove every AI-related environment variable, then restore them."""

    def __enter__(self):
        self.saved = {k: os.environ.pop(k) for k in _AI_ENV if k in os.environ}

    def __exit__(self, *exc):
        for k in _AI_ENV:
            os.environ.pop(k, None)
        os.environ.update(self.saved)


def test_ai_true_adds_the_hint_to_the_output():
    cmp = compare_traces(user_buggy, user_reference, args=([12, 3, 40, 8], 5, 50),
                  ai=lambda prompt: "Look at what remove returns.\nWhat do you expect it to give back?")
    assert cmp.ai_hint.startswith("Look at what remove returns")
    assert "AI hint:" in str(cmp) and "What do you expect" in str(cmp)
    assert "AI hint" in cmp._repr_html_()


def test_a_failing_model_never_breaks_the_comparison():
    def broken(prompt):
        raise ConnectionError("offline")

    cmp = compare_traces(user_buggy, user_reference, args=([12, 3, 40, 8], 5, 50), ai=broken)
    assert cmp.divergence is not None and cmp.ai_hint is None
    assert "AI hint unavailable" in str(cmp) and "offline" in str(cmp)


def test_ai_true_without_any_key_says_what_to_do():
    import sys

    with _clean_ai_env():
        sys.modules.pop("hermes_acp_sdk", None)
        cmp = compare_traces(user_buggy, user_reference, args=([12, 3, 40, 8], 5, 50), ai=True)
    assert cmp.ai_hint is None and "DEEPSEEK_API_KEY" in cmp.ai_error


def test_keys_and_defaults_are_read_from_the_environment():
    from difffinder import openai_compatible

    with _clean_ai_env():
        os.environ["DEEPSEEK_API_KEY"] = "k"
        ask = openai_compatible()
        assert ask.url == "https://api.deepseek.com/chat/completions" and ask.model == "deepseek-chat"
    with _clean_ai_env():
        os.environ["OPENAI_API_KEY"] = "k"
        try:
            openai_compatible()
        except RuntimeError as exc:
            assert "DIFFFINDER_MODEL" in str(exc)
        else:
            assert False, "an OpenAI key needs an explicit model name"
        os.environ["OPENAI_MODEL"] = "some-model"
        ask = openai_compatible()
        assert ask.url == "https://api.openai.com/v1/chat/completions" and ask.model == "some-model"


def test_prompt_contains_the_evidence_a_model_needs():
    from difffinder.ai import build_prompt

    cmp = compare_traces(user_buggy, user_reference, args=([12, 3, 40, 8], 5, 50))
    prompt = build_prompt(cmp)
    for needed in ("def user_buggy", "def user_reference", "never quote or describe it",
                   "VALUES OF 'nums'", "LAST CHANGES", "[12, 3, 40, 8]", "nums = nums.remove(y)"):
        assert needed in prompt, needed
    assert "REFERENCE FUNCTION" not in build_prompt(cmp, share_reference=False)


# ---- probing: different algorithms, other inputs, smallest failing case ---------------------------

def test_probe_finds_a_failing_input_even_when_yours_passes_on_the_one_given():
    def abs_bad(x):
        return x

    def abs_ok(x):
        return -x if x < 0 else x

    cmp = compare_traces(abs_bad, abs_ok, args=(5,))
    assert not cmp.outcomes_differ and not cmp.same
    assert cmp.probe.minimal == (-1,)
    assert any("negative" in line for line in cmp.probe.patterns)
    assert "agree on your input" in str(cmp)


def test_two_correct_solutions_written_differently_are_the_same():
    def ascending(n):
        total = 0
        for i in range(n):
            total += i
        return total

    def shifted(n):
        total = 0
        for i in range(n):
            total += i + 1  # a different path to the same answer
        return total - max(n, 0)

    cmp = compare_traces(ascending, shifted, args=(4,))
    assert cmp.same and cmp.divergence is None
    assert cmp.probe.failing == 0


def test_the_failing_input_is_shrunk_to_the_smallest_case():
    cmp = compare_traces(sum_off_by_one, sum_ok, args=(50,))
    assert cmp.probe.minimal == (1,)
    assert "Smallest failing input" in str(cmp)


def test_a_high_crash_rate_is_reported():
    cmp = compare_traces(user_buggy, user_reference, args=([12, 3, 40, 8], 5, 50))
    assert any("AttributeError" in line and "of the" in line for line in cmp.probe.patterns)
    assert len(cmp.probe.minimal[0]) <= 1  # the list was shrunk


def test_probe_can_be_switched_off_and_its_runs_stay_quiet():
    import contextlib
    import io

    def talkative(x):
        print("hi")
        return x

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        compare_traces(talkative, talkative, args=(1,))
    assert buffer.getvalue() == "hi\nhi\n"  # once per function; the probe's many runs are silent
    assert compare_traces(talkative, talkative, args=(1,), probe=False).probe is None
