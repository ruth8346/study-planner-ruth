"""USD per million tokens, used by both versions so their costs are computed the same way.

Cache writes cost 1.25x the input price with the 5-minute TTL (what API/harness/caching.py
uses) and 2x with the 1-hour TTL (what Claude Code uses).
"""

PRICES = {
    # model: (input, output, cache_read)
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}
WRITE_MULTIPLIER = {"5m": 1.25, "1h": 2.0}


def cost_usd(model: str, input_tokens: int, output_tokens: int, cache_read: int, cache_write: int,
             cache_ttl: str = "5m") -> float:
    for name, price in PRICES.items():
        if model.startswith(name):
            p_in, p_out, p_read = price
            break
    else:
        raise KeyError(f"no price for model {model}")
    p_write = p_in * WRITE_MULTIPLIER[cache_ttl]
    return (input_tokens * p_in + output_tokens * p_out + cache_read * p_read + cache_write * p_write) / 1_000_000
