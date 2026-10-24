"""Outgoing mail (invites, password resets) through Resend's HTTP API, as plain text.

Plain text on purpose: there is no HTML for click tracking to rewrite, so links reach the
reader unchanged (keep tracking off on the sending domain). Without RESEND_API_KEY and
MAIL_FROM there is no mail, and every caller still has the copyable link. Never call inside
`transaction()`.
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"
TRANSPORT: httpx.BaseTransport | None = None  # tests swap in an httpx.MockTransport


def configured() -> bool:
    return bool(os.environ.get("RESEND_API_KEY") and os.environ.get("MAIL_FROM"))


def send(to: str, subject: str, text: str) -> bool:
    """True when Resend accepted the message; False when mail is off or sending failed (logged)."""
    if not configured():
        return False
    try:
        with httpx.Client(transport=TRANSPORT, timeout=15) as client:
            client.post(
                RESEND_URL,
                headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
                json={"from": os.environ["MAIL_FROM"], "to": [to], "subject": subject, "text": text},
            ).raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("Mail to %s not sent: %s", to, e)
        return False
    return True
