"""Conservative decimal accumulation for persisted finite float-denominated costs."""
from decimal import Decimal, ROUND_CEILING, localcontext


def sum_costs(values) -> Decimal:
    # A binary64 value converted via str spans at most ~633 decimal places,
    # including subnormals. This precision also accommodates the bounded call
    # count; ceiling rounding prevents underestimation if that assumption changes.
    with localcontext() as ctx:
        ctx.prec = 1000
        ctx.rounding = ROUND_CEILING
        return sum((v if isinstance(v, Decimal) else Decimal(str(v)) for v in values), Decimal(0))
