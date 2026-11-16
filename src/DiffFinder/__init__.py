"""DiffFinder: check a Python function against a reference solution and see how they differ.

>>> from difffinder import compare
>>> compare(my_function, reference_function, args=(4,))
"""

from .comparison import Comparison, Difference, compare
from .outcome import Outcome, run

__version__ = "0.1.0"

__all__ = ["compare", "run", "Comparison", "Difference", "Outcome", "__version__"]
