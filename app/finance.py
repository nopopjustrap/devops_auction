"""Pure financial rules: integer kopecks and basis points."""


def commission_kopecks(price_kopecks: int, rate_bps: int) -> int:
    """Round half up to a kopeck. 10000 basis points = 100 percent."""
    if price_kopecks <= 0:
        raise ValueError("Price must be positive")
    if not 0 <= rate_bps <= 10000:
        raise ValueError("Commission must be between 0 and 10000 basis points")
    return (price_kopecks * rate_bps + 5000) // 10000
