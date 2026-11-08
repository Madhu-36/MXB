"""Single source of truth for the MXB version (installer, updater, diagnostics, README)."""
__version__ = "4.3.0"


def parse_version(text: str) -> tuple[int, ...]:
    """'v4.1.0' / '4.1' / '4.1.0-beta' -> (4, 1, 0). Non-numeric parts are ignored."""
    core = str(text or "").strip().lstrip("vV").split("-")[0].split("+")[0]
    parts = []
    for piece in core.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def is_newer(candidate: str, current: str = __version__) -> bool:
    return parse_version(candidate) > parse_version(current)
