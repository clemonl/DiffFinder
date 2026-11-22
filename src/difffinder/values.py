"""Value comparison helpers shared by direct and trace comparisons."""

from __future__ import annotations

import ast
import math
import numbers
from decimal import Decimal
from fractions import Fraction
from typing import Any, Optional


def validate_tolerance(tolerance: Optional[float]) -> None:
    """Validate an optional non-negative finite numeric tolerance."""
    if tolerance is None:
        return
    if isinstance(tolerance, bool) or not isinstance(tolerance, (numbers.Real, Decimal)):
        raise TypeError("tolerance must be a non-negative finite number or None")
    if isinstance(tolerance, Decimal):
        finite = tolerance.is_finite()
    else:
        finite = math.isfinite(tolerance)
    if not finite or tolerance < 0:
        raise ValueError("tolerance must be non-negative and finite")


def _is_numeric(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (numbers.Number, Decimal))


def _within_tolerance(a: Any, b: Any, tolerance: float) -> bool:
    try:
        return abs(a - b) <= tolerance
    except TypeError:
        if isinstance(a, Decimal) or isinstance(b, Decimal):
            return abs(Decimal(str(a)) - Decimal(str(b))) <= Decimal(str(tolerance))
        raise


def same_value(a: Any, b: Any, tolerance: Optional[float] = None) -> bool:
    """Compare values, applying tolerance only to corresponding numeric values."""
    if tolerance is None:
        try:
            return bool(a == b)
        except Exception:
            return repr(a) == repr(b)

    if _is_numeric(a) and _is_numeric(b):
        try:
            if bool(a == b):
                return True
        except Exception:
            pass
        try:
            return bool(_within_tolerance(a, b, tolerance))
        except (ArithmeticError, TypeError, ValueError):
            try:
                return bool(a == b)
            except Exception:
                return repr(a) == repr(b)

    if type(a) is type(b) and isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(same_value(x, y, tolerance) for x, y in zip(a, b))
    if type(a) is type(b) and isinstance(a, dict):
        return a.keys() == b.keys() and all(same_value(a[key], b[key], tolerance) for key in a)

    try:
        return bool(a == b)
    except Exception:
        return repr(a) == repr(b)


def same_repr(a: str, b: str, tolerance: Optional[float] = None) -> bool:
    """Compare recorded repr values, parsing literals only when tolerance is enabled."""
    if tolerance is None or a == b:
        return a == b
    try:
        left, right = ast.literal_eval(a), ast.literal_eval(b)
    except (SyntaxError, ValueError):
        try:
            left = _parse_recorded_value(ast.parse(a, mode="eval").body)
            right = _parse_recorded_value(ast.parse(b, mode="eval").body)
        except (SyntaxError, ValueError, TypeError):
            return False
    return same_value(left, right, tolerance)


def _parse_recorded_value(node: ast.AST) -> Any:
    """Parse trace reprs containing only literals and standard numeric constructors."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.List):
        return [_parse_recorded_value(item) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_parse_recorded_value(item) for item in node.elts)
    if isinstance(node, ast.Set):
        return {_parse_recorded_value(item) for item in node.elts}
    if isinstance(node, ast.Dict):
        return {
            _parse_recorded_value(key): _parse_recorded_value(value)
            for key, value in zip(node.keys, node.values)
        }
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _parse_recorded_value(node.operand)
        return +value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        args = [_parse_recorded_value(arg) for arg in node.args]
        if node.func.id == "Decimal" and len(args) == 1:
            return Decimal(args[0])
        if node.func.id == "Fraction" and len(args) in (1, 2):
            return Fraction(*args)
    raise ValueError("unsupported recorded value")
