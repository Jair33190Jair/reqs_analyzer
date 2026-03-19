# Anthropic model pricing — $ per million tokens
# Update when prices change: https://www.anthropic.com/pricing
_PRICING: dict[str, tuple[float, float]] = {
    # (input $/MTok, output $/MTok)
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-opus-4-5-20251001":   (15.00, 75.00),
    "claude-sonnet-4-6":   (3.00, 15.00),
}


def get_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return the USD cost for a message given token counts.
    Raises KeyError if the model is not in the pricing table."""
    in_price, out_price = _PRICING[model]
    return (input_tokens * in_price + output_tokens * out_price) / 1_000_000
