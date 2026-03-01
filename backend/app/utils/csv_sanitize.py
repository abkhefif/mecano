def sanitize_csv_cell(value: str | None) -> str | None:
    """Sanitize a string value to prevent CSV/Excel formula injection.

    If the value starts with a character that Excel or other spreadsheet
    applications interpret as a formula prefix, prepend a single quote to
    neutralize it.
    """
    if value is None:
        return None
    if isinstance(value, str) and value and value[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value
