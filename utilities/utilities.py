




import decimal


def num_or_zero(value):
    """
    Returns the value if it is numeric (int, float), or converts decimal.Decimal to float.
    Otherwise returns 0.
    """
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, decimal.Decimal):
        return float(value)
    return 0

def to_number_or_zero(value):
    """
    Tries to convert the value to a number. If it fails, returns 0.
    """
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0