"""DiffFinder: check a Python function against a reference solution and see how they differ.

>>> from difffinder import compare
>>> compare(my_function, reference_function, args=(4,))
"""

from .comparison import Comparison, Difference, compare
from .ai import explain, hermes_llm, openai_compatible
from .diff import Divergence, TraceComparison, compare_traces, find_difference, find_divergence
from .outcome import Outcome, run
from .selfcheck import selfcheck
from .tracer import RAISE, RETURN, Event, StepLimitExceeded, Trace, record

__version__ = "0.1.0"

__all__ = [
    "compare", "run", "Comparison", "Difference", "Outcome",
    "compare_traces", "TraceComparison", "Divergence", "find_difference", "find_divergence",
    "record", "Trace", "Event", "StepLimitExceeded", "RETURN", "RAISE",
    "explain", "openai_compatible", "hermes_llm", "selfcheck", "__version__",
]
