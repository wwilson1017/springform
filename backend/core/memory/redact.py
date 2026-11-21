"""Secrets never enter memory: each password, API key, private key and card number in a fact or a
context file becomes `[removed: <kind>]`, and the write says what went (never the values).

Lifted from gtd-suite `backend/brain.py` (`_SECRETS`, `_blank_secrets`, `_luhn`, `_removed`).
"""

from __future__ import annotations

import bisect
import re
from collections import Counter

# Each kind with its patterns. A group 1 is kept: "password: " stays and only the value goes.
_SECRETS = (
    # A whole private key, through its END line (or the end of the text, if it has none).
    ("key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----(?:.*?-----END [A-Z ]*PRIVATE KEY-----|.*)", re.I | re.S)),
    (
        "key",
        re.compile(
            r"\b(?:sk|rk)[-_](?:live|test|proj|ant[-_]api\d*)?[-_]?[A-Za-z0-9_-]{20,}"
            r"|\bAKIA[0-9A-Z]{16}\b|\bgh[pousr]_[A-Za-z0-9]{30,}|\bxox[abprs]-[A-Za-z0-9-]{10,}"
            r"|\bAIza[0-9A-Za-z_-]{35}",
            re.I,
        ),
    ),
    # 'password: "correct horse"': a quoted value is a password whatever it holds (added here)
    ("password", re.compile(r"(\b(?:password|passwd|passcode)\s*(?:is|:|=)\s*)([\"'])[^\"'\n]{4,}?\2", re.I)),
    # "password: correcthorse": after a colon or equals sign any value of 6+ characters (added here)
    ("password", re.compile(r"(\b(?:password|passwd|passcode)\s*[:=]\s*[\"']?)(?!\[removed)[^\s\"']{6,}", re.I)),
    # "password is hunter22", a value with a digit or a symbol, not "is in 1Password"
    (
        "password",
        re.compile(
            r"(\b(?:password|passwd|passcode)\s*(?:is|:|=)\s*[\"']?)"
            r"(?=[^\s\"']*[\d!@#$%^&*])[^\s\"']{6,}",
            re.I,
        ),
    ),
)
# A card number: 13 to 19 digits, single spaces or dashes between, with clean edges: not after
# + @ : / = # _ - or a letter, nor before @ / : - or a letter, so not a phone number (+1…), a
# path, a UUID's piece or part of a hex run. `_is_card` adds the Luhn check and a card prefix
# (Visa, Mastercard, Amex, Discover); a number inside a URL word is left alone.
_CARD = re.compile(r"(?<![\w+@:/=#-])(?:\d[ -]?){12,18}\d(?![\w@/:-])")
_CARD_PREFIX = re.compile(r"4|5[1-5]|2(?:22[1-9]|2[3-9]\d|[3-6]\d\d|7[01]\d|720)|3[47]|6(?:011|5|4[4-9])")
_URL = re.compile(r"://|www\.", re.I)


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


def _is_card(digits: str) -> bool:
    return 13 <= len(digits) <= 19 and bool(_CARD_PREFIX.match(digits)) and _luhn(digits)


def blank_secrets(text: str) -> tuple[str, Counter]:
    """`text` with each secret replaced by `[removed: <kind>]`, and how many of each kind went."""
    removed: Counter = Counter()

    def blank(kind):
        def repl(m):
            removed[kind] += 1
            return (m.group(1) if m.re.groups else "") + f"[removed: {kind}]"

        return repl

    for kind, pattern in _SECRETS:
        text = pattern.sub(blank(kind), text)
    card = blank("card number")
    # The URL words, found once (sorted, disjoint): a card match touching one is left alone.
    urls = [w.span() for w in re.finditer(r"\S+", text) if _URL.search(w.group())]
    starts = [u[0] for u in urls]

    def in_url(m):
        for pos in (m.start(), m.end() - 1):
            i = bisect.bisect_right(starts, pos) - 1
            if i >= 0 and pos < urls[i][1]:
                return True
        return False

    return _CARD.sub(
        lambda m: card(m) if _is_card(re.sub(r"\D", "", m.group())) and not in_url(m) else m.group(), text
    ), removed


def removed_list(counts: Counter) -> list[dict]:
    """A write's `removed`: the kinds blanked out and how many, never the values."""
    return [{"kind": k, "count": n} for k, n in counts.items()]
