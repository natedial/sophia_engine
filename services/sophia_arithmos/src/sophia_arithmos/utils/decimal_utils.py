"""Decimal precision utilities."""

from decimal import Decimal, ROUND_HALF_UP
from typing import Union

from ..config import settings
from ..core.types import PrecisionType


def get_precision_for_type(precision_type: PrecisionType) -> int:
    """Get the decimal precision for a given precision type."""
    precision_map = {
        PrecisionType.RATE: settings.precision.rate,
        PrecisionType.PERCENT: settings.precision.percent,
        PrecisionType.INDEX: settings.precision.index,
        PrecisionType.RATIO: settings.precision.ratio,
        PrecisionType.CURRENCY: settings.precision.currency,
        PrecisionType.DEFAULT: settings.precision.default,
    }
    return precision_map.get(precision_type, settings.precision.default)


def quantize_decimal(
    value: Union[Decimal, float, int, str],
    precision: int,
) -> Decimal:
    """Quantize a value to specified decimal places.

    Args:
        value: The value to quantize
        precision: Number of decimal places

    Returns:
        Quantized Decimal value
    """
    if not isinstance(value, Decimal):
        value = Decimal(str(value))

    quantize_str = "0." + "0" * precision if precision > 0 else "0"
    return value.quantize(Decimal(quantize_str), rounding=ROUND_HALF_UP)


def round_to_precision(
    value: Union[Decimal, float, int, str],
    precision_type: PrecisionType = PrecisionType.DEFAULT,
) -> float:
    """Round a value to the precision specified by type.

    Args:
        value: The value to round
        precision_type: Which precision setting to use

    Returns:
        Rounded float value
    """
    precision = get_precision_for_type(precision_type)
    quantized = quantize_decimal(value, precision)
    return float(quantized)


def format_with_precision(
    value: Union[Decimal, float, int, str],
    precision_type: PrecisionType = PrecisionType.DEFAULT,
) -> str:
    """Format a value as a string with appropriate precision.

    Args:
        value: The value to format
        precision_type: Which precision setting to use

    Returns:
        Formatted string representation
    """
    precision = get_precision_for_type(precision_type)
    quantized = quantize_decimal(value, precision)
    return f"{quantized:.{precision}f}"
