# DiffFinder

**Check a Python function against a reference solution and see exactly how they differ.**

Give DiffFinder your function and a known-good one. It runs both on the same input and tells you whether they
behave the same, and if not, what is different: the result, an exception, or a change to the input.

```text
pip install tracecomparekit
```

## Motivation

When a program gives the wrong answer, a beginner often cannot tell *what* is wrong, only that something is.
But frequently a correct solution already exists (the lecturer's, a textbook's, a classmate's). Then the useful
question is not "what does my code do?" but **"how does my code's behaviour differ from the right one?"**

## What makes it different

- **You supply a reference function, not hand-written expected values.** There is nothing to calculate by hand,
  and the reference can be written in any style.
- **It compares behaviour, not source code.** A loop and a formula that give the same answers are reported as the
  same. A text diff of the two would be useless.
- **It catches what a printed return value hides:** a function that crashes where the reference does not, or one
  that changes its input list in place when the reference leaves it alone.
- **No dependencies**, so it installs next to anything, including on a shared notebook server.

## Quick start

```python
from difffinder import compare

def count_to(n):            # your version
    total = 0
    for i in range(n):
        total += i
    return total

def count_to_ref(n):        # the reference
    total = 0
    for i in range(n + 1):
        total += i
    return total

compare(count_to, count_to_ref, args=(4,))
```

```text
DIFFERENT: count_to and count_to_ref behave differently on (n=4).
  result: yours returned 6, the reference returned 10.
```

Different algorithms with the same behaviour are reported as the same:

```python
def formula(n):
    return n * (n + 1) // 2

compare(count_to_ref, formula, args=(4,))
```

```text
SAME: count_to_ref and formula behave the same on (n=4).
```

Crashes and changes to the input are shown too:

```python
def sort_in_place(items):
    items.sort()
    return items

def sorted_copy(items):
    return sorted(items)

compare(sort_in_place, sorted_copy, args=([3, 1, 2],))
```

```text
DIFFERENT: sort_in_place and sorted_copy behave differently on (items=[3, 1, 2]).
  argument 'items' afterwards: yours [1, 2, 3], the reference [3, 1, 2].
```

```python
def first_item(items):
    return items[0]

def first_or_none(items):
    return items[0] if items else None

compare(first_item, first_or_none, args=([],))
```

```text
DIFFERENT: first_item and first_or_none behave differently on (items=[]).
  result: yours raised IndexError: list index out of range, the reference returned None.
```

## Usage

```python
compare(candidate, reference, args=(), kwargs=None)
```

| Part | Meaning |
| --- | --- |
| `candidate` | your function (the one you want to check) |
| `reference` | the known-good function |
| `args` | a tuple of positional arguments, for example `(4,)` or `([3, 1, 2], 5)` (note the comma in a one-item tuple) |
| `kwargs` | a dict of keyword arguments, for example `{"reverse": True}` |

It returns a `Comparison` with `.same` (`True` or `False`), `.differences` (a list), and `.candidate` /
`.reference`, which hold what each function did. `run(func, args)` runs a single function and records the same
information.

### When are two functions "the same"?

On the input you give, they must have:

1. the same return value (compared with `==`), or both raise the same kind of exception, and
2. the same final state of every argument they received.

Each function runs on its own deep copy of your arguments, so your data is never changed.

## Limitations

- It checks **one input per call**. A function can match on your input and still be wrong on another, so try
  several (such as an empty list, zero, or a negative number).
- The functions must finish. It cannot yet stop an endless loop.
- Anything a function does besides returning or changing its arguments (printing, files, network) happens once
  per function.
- Parameters are matched by position, so the two functions may use different parameter names.

## Trace a difference

`compare_traces()` records changes to local variables and shows where the two runs first
diverge. The report displays as text in the terminal and as a table in Jupyter.

```python
from difffinder import compare_traces, find_difference

report = compare_traces(count_to, count_to_ref, args=(4,), probe=False)
print(report)

first = find_difference(count_to, count_to_ref, [0, 1, 4])
print(first.args)  # (1,)
```

By default, `compare_traces()` also runs the functions on variations of the positional inputs
and tries to shrink a failing example. Use `probe=False` to run each function once.
Pass `watch=["total"]` to compare a particular variable. Offline hints appear in the report.
For an optional model-generated hint, pass `ai=your_callable`. The callable receives a prompt
containing the functions' source, input, and comparison report.

## Sorting visualizer

With Tkinter installed, run `python -m difffinder.sorting_visualizer`. Choose two sorting
functions, enter a list, and click **Compare & Record** to step through their changes side by side.
For a terminal example, run `python -m difffinder.demo --console`.

## Development

```text
git clone https://github.com/clemonl/DiffFinder
cd difffinder
pip install -e ".[dev]"
pytest
```

Requirements are listed in [SPEC.md](SPEC.md) and the division of work in [TEAM.md](TEAM.md).
Released under the MIT license.
