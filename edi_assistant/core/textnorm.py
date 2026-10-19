"""Text normalisation helpers."""
from __future__ import annotations

import re
import unicodedata

_STOP = {"co", "ltd", "limited", "company", "inc", "corp", "corporation", "the", "llc"}


def normalize_header(s: object) -> str:
    """'G.W.(KGS)' -> 'gw kgs'; '品名/Description' -> '品名 description'."""
    t = unicodedata.normalize("NFKC", "" if s is None else str(s)).lower().replace("\n", " ")
    # '.' is dropped (G.W. -> gw); other separators become spaces
    t = t.replace(".", "")
    t = "".join(ch if ch.isalnum() or ch == " " else " " for ch in t)
    return re.sub(r"\s+", " ", t).strip()


def header_tokens(s: str) -> list[str]:
    return normalize_header(s).split()


def normalize_company(s: str) -> str:
    t = unicodedata.normalize("NFKC", s or "").lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return " ".join(w for w in t.split() if w not in _STOP)


def token_set(s: str) -> set[str]:
    return set(s.split())


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)
