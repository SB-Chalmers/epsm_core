"""Bounded plain-text summaries of already loaded domain metadata.

This helper formats scalar labels and counts. It never traverses domain graphs,
serializes objects, computes identities or performs I/O.
"""


def _short_value(value, budget):
    if isinstance(value, str):
        # Clip the raw string before escaping, then reduce by whole characters.
        # This preserves complete escape sequences and balanced quotes.
        stop = min(len(value), budget)
        while stop >= 0:
            text = repr(value[:stop] + ("…" if stop < len(value) else ""))
            if len(text) <= budget:
                return text
            stop -= 1
    if value is None or isinstance(value, (bool, int, float)):
        return repr(value)
    return "<object>"


def bounded_summary(name, **fields):
    """Format a single-line summary of at most 160 characters, including escapes."""
    name = name if len(name) <= 40 else name[:39] + "…"
    for budget in (48, 32, 24, 16, 8):
        parts = [f"{key}={_short_value(value, budget)}" for key, value in fields.items()]
        text = f"{name}({', '.join(parts)})"
        if len(text) <= 160:
            return text
    # Keep a valid summary even for a future caller supplying too many fields.
    while parts:
        parts.pop()
        text = f"{name}({', '.join((*parts, '…'))})"
        if len(text) <= 160:
            return text
    return f"{name}(…)"
