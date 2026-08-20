from decimal import Decimal, ROUND_HALF_UP


USD_QUANT = Decimal("0.01")
SYP_QUANT = Decimal("1")


def quantize_usd(amount: Decimal) -> Decimal:
    return amount.quantize(
        USD_QUANT,
        rounding=ROUND_HALF_UP,
    )


def quantize_syp(amount: Decimal) -> Decimal:
    return amount.quantize(
        SYP_QUANT,
        rounding=ROUND_HALF_UP,
    )


def convert_syp_to_usd(
    amount_syp: Decimal,
    exchange_rate_syp_per_usd: Decimal,
) -> Decimal:
    if amount_syp <= 0:
        raise ValueError(
            "يجب أن يكون المبلغ بالليرة أكبر من صفر."
        )

    if exchange_rate_syp_per_usd <= 0:
        raise ValueError(
            "يجب أن يكون سعر الصرف أكبر من صفر."
        )

    return quantize_usd(
        amount_syp
        / exchange_rate_syp_per_usd
    )


def convert_usd_to_syp(
    amount_usd: Decimal,
    exchange_rate_syp_per_usd: Decimal,
) -> Decimal:
    if amount_usd < 0:
        raise ValueError(
            "لا يمكن أن يكون المبلغ بالدولار سالبًا."
        )

    if exchange_rate_syp_per_usd <= 0:
        raise ValueError(
            "يجب أن يكون سعر الصرف أكبر من صفر."
        )

    return quantize_syp(
        amount_usd
        * exchange_rate_syp_per_usd
    )