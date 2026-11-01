from __future__ import annotations

import unicodedata


def key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    words = normalized.split()
    collapsed = " ".join(words)
    return collapsed.casefold()
