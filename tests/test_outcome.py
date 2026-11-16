from difffinder import run


def double(x):
    return x * 2


def test_records_the_return_value():
    out = run(double, (4,))
    assert out.returned == 8 and not out.raised
    assert out.describe() == "returned 8"


def test_records_an_exception_instead_of_raising_it():
    def fails(x):
        return 1 / x

    out = run(fails, (0,))
    assert out.raised and out.error_type == "ZeroDivisionError"
    assert out.describe().startswith("raised ZeroDivisionError")


def test_keyword_arguments_work():
    def greet(name, punctuation="!"):
        return name + punctuation

    assert run(greet, ("Sam",), {"punctuation": "?"}).returned == "Sam?"


def test_the_callers_data_is_never_changed():
    def empty_it(items):
        items.clear()
        return len(items)

    data = [1, 2, 3]
    out = run(empty_it, (data,))
    assert data == [1, 2, 3]  # untouched
    assert out.arguments["items"] == []  # but the change the function made is recorded


def test_inputs_are_recorded_by_parameter_name():
    out = run(lambda a, b: a + b, (1, 2))
    assert out.inputs == {"a": "1", "b": "2"}


def test_rebinding_a_parameter_name_is_not_a_change_to_the_argument():
    def rebinds(items):
        items = []  # a new list; the caller's list is not changed
        return items

    assert run(rebinds, ([1, 2],)).arguments["items"] == [1, 2]
