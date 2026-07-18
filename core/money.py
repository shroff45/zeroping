"""
core/money.py — Indian-format Indian Rupee formatter + Decimal helpers.

Pure string arithmetic. No locale module (OS-dependent, breaks on Windows).
No cleverness. Deterministic.

Indian grouping rule (right-to-left):
  - Take the last 3 digits as the first group.
  - Then every 2 digits leftward is a new group.
  - Join with commas.

  185000   → 1,85,000       (lakh)
  12000000 → 1,20,00,000   (crore)
  1500     → 1,500          (thousands — Indian system still uses 3-digit first group)
  0        → 0

Negative: minus goes BEFORE the symbol, never between symbol and magnitude.
  -12000 → "-₹12,000"  (not "₹-12,000")

Rounding: Python's round() uses banker's rounding for .5 ties.
The test suite expects round-half-UP (184_999.999 → 185_000).
We implement explicit round-half-up via Decimal to be unambiguous.

──────────────────────────────────────────────────────────────────────
DECIMAL HELPERS (engine compute boundary)
──────────────────────────────────────────────────────────────────────
Engines receive floats from the snapshot (JSON-serializable wire format),
immediately cast to Decimal via to_decimal(), compute in Decimal,
cast back to float on return.

This is the correctness boundary. The cast-to-float is explicit and
documented. It is not an accident. It is the boundary.

Pattern in every engine:
  cash = to_decimal(snap.cash_balance)
  result = ...compute in Decimal...
  return SomeResult(field=float(result), ...)
"""

from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP, getcontext

# Set global Decimal precision to 28 (IBM decNumber standard)
getcontext().prec = 28

_ZERO = Decimal("0")
_ONE  = Decimal("1")


# ── Decimal helpers ───────────────────────────────────────────────────

def to_decimal(value: float | int | str | Decimal) -> Decimal:
    """
    Convert any numeric value to Decimal with 28-digit precision.
    Use repr(float) to avoid binary floating-point representation errors.

    Examples:
        to_decimal(67000.0)    → Decimal('67000')
        to_decimal(185000.0)   → Decimal('185000')
        to_decimal("67000.0")  → Decimal('67000.0')
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def safe_divide(numerator: Decimal, denominator: Decimal, default: Decimal = _ZERO) -> Decimal:
    """
    Decimal division that returns default instead of raising ZeroDivisionError.

    Args:
        numerator:   Decimal numerator.
        denominator: Decimal denominator.
        default:     Value to return if denominator is zero. Default: Decimal('0').

    Returns:
        numerator / denominator, or default if denominator == 0.
    """
    if denominator == _ZERO:
        return default
    return numerator / denominator


def d_sum(values) -> Decimal:
    """
    Sum an iterable of numeric values as Decimal.
    Avoids float accumulation errors.
    """
    total = _ZERO
    for v in values:
        total += to_decimal(v)
    return total


# ── Indian rupee formatter ────────────────────────────────────────────

def format_inr(
    amount: float,
    symbol: str = "₹",
    paise: bool = False,
) -> str:
    """
    Format a numeric amount as an Indian-grouped rupee string.

    Args:
        amount:      Any real number.
        symbol:      Currency prefix. Default "₹".
                     For LLM prompts use symbol="Rs. " (₹ tokenises poorly).
        paise:       If True, append .XX decimal part (omitted when .00).

    Returns:
        Formatted string, e.g. "₹1,85,000" or "-₹12,000" or "Rs. 1,85,000".

    Examples:
        format_inr(185_000)            -> "₹1,85,000"
        format_inr(12_000_000)         -> "₹1,20,00,000"
        format_inr(67_000)             -> "₹67,000"
        format_inr(1_500)              -> "₹1,500"
        format_inr(-12_000)            -> "-₹12,000"
        format_inr(184_999.999)        -> "₹1,85,000"   # round-half-up
        format_inr(0)                  -> "₹0"
        format_inr(185_000, "Rs. ")    -> "Rs. 1,85,000"
        format_inr(1_500.50, paise=True) -> "₹1,500.50"
        format_inr(1_500.00, paise=True) -> "₹1,500"
    """
    # Quantize with round-half-UP (explicit, not banker's rounding).
    # 2 decimal places when paise, otherwise 0 decimals (rupees only).
    quant = Decimal("0.01") if paise else Decimal("1")
    d = Decimal(repr(float(amount))).quantize(quant, rounding=ROUND_HALF_UP)

    # Split out sign and magnitude
    is_neg = d < 0
    d_abs = abs(d)

    # Decimal (paise) part, if requested
    rupees_int = int(d_abs)                          # truncate toward zero
    paise_int = int((d_abs - rupees_int) * 100)      # exactly 0..99

    # Apply Indian grouping to the rupees integer
    grouped = _indian_group(rupees_int)

    # Decimal suffix
    decimal_suffix = ""
    if paise and paise_int > 0:
        decimal_suffix = f".{paise_int:02d}"
    elif paise and paise_int == 0:
        decimal_suffix = ""   # test_paise_zero: "₹1,500" not "₹1,500.00"

    return f"{'-' if is_neg else ''}{symbol}{grouped}{decimal_suffix}"


def _indian_group(n: int) -> str:
    """
    Group a non-negative integer using the Indian system:
    last 3 digits first, then pairs leftward.
      0          -> "0"
      500        -> "500"
      1500       -> "1,500"
      67000      -> "67,000"
      185000     -> "1,85,000"
      12000000   -> "1,20,00,000"
    """
    if n == 0:
        return "0"

    s = str(n)
    # Strip leading zeros (defensive; Decimal path shouldn't produce them)
    s = s.lstrip("0") or "0"

    if len(s) <= 3:
        return s

    # First group: rightmost 3 digits.
    # Remaining groups: every 2 digits from the right of what's left.
    first = s[-3:]
    rest = s[:-3]

    # Piece rest into 2-digit chunks from the right.
    groups = []
    while len(rest) > 2:
        groups.append(rest[-2:])
        rest = rest[:-2]
    if rest:
        groups.append(rest)
    groups.reverse()  # left-to-right order

    return ",".join(groups + [first])


# ── Quick self-test (manual verification, not pytest) ─────────────────
if __name__ == "__main__":
    # Mirror tests/test_money.py so `python -m core.money` verifies the contract
    cases = [
        (185_000,              "₹1,85,000"),
        (12_000_000,           "₹1,20,00,000"),
        (67_000,               "₹67,000"),
        (1_500,                "₹1,500"),
        (-12_000,             "-₹12,000"),
        (184_999.999,          "₹1,85,000"),
        (0,                    "₹0"),
        # paise variants
        (1_500.50,             "₹1,500.50", "paise"),
        (1_500.00,             "₹1,500",    "paise"),
        # non-default symbol
        (185_000,              "Rs. 1,85,000", "symbol"),
    ]
    failed = 0
    for row in cases:
        amt = row[0]
        expected = row[1]
        mode = row[2] if len(row) > 2 else ""
        if mode == "paise":
            got = format_inr(amt, paise=True)
        elif mode == "symbol":
            got = format_inr(amt, symbol="Rs. ")
        else:
            got = format_inr(amt)
        ok = "✓" if got == expected else "✗"
        if got != expected:
            failed += 1
        print(f"{ok} {amt:>12} -> {got!r:<18} expected {expected!r}")

    # Decimal helpers
    print()
    assert to_decimal(67000.0) == Decimal("67000")
    assert safe_divide(Decimal("10"), Decimal("0")) == Decimal("0")
    assert safe_divide(Decimal("10"), Decimal("2")) == Decimal("5")
    print("✓ to_decimal and safe_divide OK")

    print()
    if failed:
        print(f"FAILED {failed} case(s)")
        raise SystemExit(1)
    print("All cases passed.")
