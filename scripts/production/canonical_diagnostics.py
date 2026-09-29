"""Exact decimal export of diagnostics; never used by strategy decisions.

Normative definition: source_of_truth/diagnostic_numeric_contract.json.
The native adapter frame remains untouched. Integer moments avoid both native
FMA contraction and cancellation in a sliding floating point variance.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from math import isqrt

SCALE = 10**12
FIELDS = ("rolling_vol_30d", "rolling_sharpe_90d")


def round_sqrt_ratio(numerator: int, denominator: int) -> int:
    """Nearest integer sqrt(N/D), with exact half-even midpoint comparison."""
    if numerator < 0 or denominator <= 0:
        raise ValueError("Invalid nonnegative square-root ratio")
    floor = isqrt(numerator // denominator)
    midpoint = denominator * (2 * floor + 1) ** 2
    difference = 4 * numerator - midpoint
    return floor + int(difference > 0 or (difference == 0 and floor % 2 == 1))


def _scaled_return(value) -> int:
    # str preserves the already published decimal lattice, rather than adding
    # binary representation error using Decimal.from_float.
    if value is None:
        return 0
    number = Decimal(str(value))
    if number.is_nan():
        return 0
    if not number.is_finite():
        raise ValueError("Infinite return in diagnostic export")
    sign, digits, exponent = number.as_tuple()
    coefficient = int(''.join(str(digit) for digit in digits))
    exponent += 12
    if exponent >= 0:
        coefficient *= 10**exponent
    else:
        coefficient, remainder = divmod(coefficient, 10**(-exponent))
        if remainder:
            raise ValueError("return_net is outside the published 12-place lattice")
    return -coefficient if sign else coefficient


def diagnostic_units(returns) -> dict[str, list[int | None]]:
    """Exact diagnostics in 10^-12 units; full windows, population variance."""
    values = [_scaled_return(value) for value in returns]
    result = {}
    for field, window in zip(FIELDS, (30, 90)):
        total = squares = 0
        output = []
        for i, value in enumerate(values):
            total += value
            squares += value * value
            if i >= window:
                removed = values[i - window]
                total -= removed
                squares -= removed * removed
            if i + 1 < window:
                output.append(None)
                continue
            dispersion = window * squares - total * total
            if dispersion < 0:
                raise ArithmeticError("Negative exact population dispersion")
            if field == FIELDS[0]:
                # scale cancels: SCALE * sqrt(1461/4 * D/(n*SCALE)^2).
                units = round_sqrt_ratio(1461 * dispersion, 4 * window * window)
            elif dispersion == 0:
                units = None
            else:
                units = round_sqrt_ratio(1461 * total * total * SCALE * SCALE, 4 * dispersion)
                if total < 0:
                    units = -units
            output.append(units)
        result[field] = output
    return result


def _decimal_units(value: int | None) -> Decimal | None:
    if value is None:
        return None
    # String construction is exact and independent of the ambient Decimal context.
    sign = "-" if value < 0 else ""
    whole, fraction = divmod(abs(value), SCALE)
    return Decimal(f"{sign}{whole}.{fraction:012d}")


def canonical_diagnostic_export(frame):
    """Copy for serialization only: no sorting, decision edits or native mutation."""
    days = [str(value) for value in frame["date"]]
    for day in days:
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError("Diagnostic export requires ISO dates")
    if any(left >= right for left, right in zip(days, days[1:])):
        raise ValueError("Diagnostic export requires unique increasing rows")
    units = diagnostic_units(frame["return_net"])
    exported = frame.copy(deep=True)
    for field in FIELDS:
        exported[field] = [_decimal_units(value) for value in units[field]]
    return exported
