import pytest

from difffinder import compare


def loop_sum(n):
    total = 0
    for i in range(n + 1):
        total += i
    return total


def formula_sum(n):
    return n * (n + 1) // 2


def off_by_one_sum(n):
    total = 0
    for i in range(n):
        total += i
    return total


def test_identical_functions_are_the_same():
    result = compare(loop_sum, loop_sum, args=(5,))
    assert result.same and result.differences == []
    assert str(result).startswith("SAME")


def test_different_algorithms_with_the_same_answer_are_the_same():
    assert compare(loop_sum, formula_sum, args=(10,)).same


def test_a_different_return_value_is_reported():
    result = compare(off_by_one_sum, loop_sum, args=(4,))
    assert not result.same
    assert result.differences[0].what == "result"
    assert "returned 6" in str(result) and "returned 10" in str(result)


def test_the_same_kind_of_exception_counts_as_the_same():
    def a(x):
        return 1 / x

    def b(x):
        return 10 / x

    assert compare(a, b, args=(0,)).same


def test_raising_versus_returning_is_a_difference():
    def crashes(xs):
        return xs[0]

    def safe(xs):
        return xs[0] if xs else None

    result = compare(crashes, safe, args=([],))
    assert not result.same
    assert "raised IndexError" in str(result) and "returned None" in str(result)


def test_a_different_change_to_an_argument_is_reported():
    def sort_in_place(xs):
        xs.sort()
        return xs

    def sorted_copy(xs):
        return sorted(xs)

    result = compare(sort_in_place, sorted_copy, args=([3, 1, 2],))
    assert [d.what for d in result.differences] == ["argument 'xs' afterwards"]
    assert "[1, 2, 3]" in str(result) and "[3, 1, 2]" in str(result)


def test_parameter_names_may_differ_between_the_two_functions():
    def mine(items):
        items.append(0)

    def theirs(values):
        values.append(1)

    result = compare(mine, theirs, args=([5],))
    assert len(result.differences) == 1 and "'items'" in result.differences[0].what


def test_the_callers_input_is_not_changed_by_comparing():
    def clear(xs):
        xs.clear()

    data = [1, 2]
    compare(clear, clear, args=(data,))
    assert data == [1, 2]


def test_values_that_cannot_be_compared_with_equals_fall_back_to_their_text():
    class Odd:
        def __eq__(self, other):
            raise TypeError("no comparing")

        def __repr__(self):
            return "Odd()"

    assert compare(lambda: Odd(), lambda: Odd()).same


def test_the_text_names_the_functions_and_the_input():
    result = compare(off_by_one_sum, loop_sum, args=(4,))
    text = str(result)
    assert "off_by_one_sum and loop_sum" in text and "n=4" in text
    assert repr(result) == text


def test_tolerance_compares_return_values_and_nested_numeric_values():
    def candidate():
        return {"values": [0.3000000001, 2]}

    def reference():
        return {"values": [0.3, 2.0]}

    assert compare(candidate, reference, tolerance=1e-9).same
    assert not compare(candidate, reference).same


def test_tolerance_keeps_exact_and_non_numeric_comparison_behaviour():
    assert compare(lambda: 0.3, lambda: 0.3, tolerance=0).same
    assert compare(lambda: "value", lambda: "value", tolerance=1).same
    assert not compare(lambda: "value", lambda: "other", tolerance=1).same
    assert not compare(lambda: 1.0, lambda: 1.2, tolerance=0.1).same


@pytest.mark.parametrize(
    ("tolerance", "error"),
    [(-1, ValueError), (float("nan"), ValueError), ("0.1", TypeError), (True, TypeError)],
)
def test_invalid_tolerance_is_rejected(tolerance, error):
    with pytest.raises(error):
        compare(lambda: 1, lambda: 1, tolerance=tolerance)
