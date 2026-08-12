"""
Email delivery adapter for garcar-payments.

Production backend uses Resend (https://resend.com).
Tests inject ``TestEmailAdapter`` which records messages in-memory and
never sends real email.

Usage::

    from app.email_adapter import get_email_adapter
    adapter = get_email_adapter()
    adapter.send_download_link("buyer@example.com", "Product Name", "https://…")
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EmailMessage:
    to: str
    subject: str
    html: str


class EmailAdapter(ABC):
    @abstractmethod
    def send_download_link(
        self,
        to: str,
        product_name: str,
        download_url: str,
        expires_in_hours: int = 24,
    ) -> None:
        ...


class ResendEmailAdapter(EmailAdapter):
    """Sends transactional email via Resend."""

    def __init__(self, api_key: str, from_address: str) -> None:
        if not api_key:
            raise ValueError("RESEND_API_KEY is required for ResendEmailAdapter")
        import resend  # noqa: PLC0415

        resend.api_key = api_key
        self._resend = resend
        self._from = from_address

    def send_download_link(
        self,
        to: str,
        product_name: str,
        download_url: str,
        expires_in_hours: int = 24,
    ) -> None:
        html = (
            f"<p>Thank you for your purchase of <strong>{product_name}</strong>.</p>"
            f"<p><a href='{download_url}'>Download your file</a></p>"
            f"<p>This link expires in {expires_in_hours} hour(s).</p>"
            f"<p>— Garcar Enterprise</p>"
        )
        self._resend.Emails.send(
            {
                "from": self._from,
                "to": to,
                "subject": f"Your {product_name} download link",
                "html": html,
            }
        )


class FakeEmailAdapter(EmailAdapter):
    """In-memory adapter used in tests.  Never sends real email."""

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    def send_download_link(
        self,
        to: str,
        product_name: str,
        download_url: str,
        expires_in_hours: int = 24,
    ) -> None:
        self.sent.append(
            EmailMessage(
                to=to,
                subject=f"Your {product_name} download link",
                html=f"<a href='{download_url}'>Download</a>",
            )
        )


# Keep the old name as an alias for backward compatibility
TestEmailAdapter = FakeEmailAdapter


# Module-level singleton — replaced by tests via ``set_email_adapter``
_adapter: Optional[EmailAdapter] = None


def get_email_adapter() -> EmailAdapter:
    global _adapter
    if _adapter is None:
        from app.settings import get_settings  # noqa: PLC0415

        s = get_settings()
        if s.resend_api_key:
            _adapter = ResendEmailAdapter(s.resend_api_key, s.email_from)
        else:
            # Fall back to no-op test adapter; warn in production
            if s.is_production():
                import sys

                print(
                    "[WARN] RESEND_API_KEY not set — email delivery disabled in production!",
                    file=sys.stderr,
                )
            _adapter = FakeEmailAdapter()
    return _adapter


def set_email_adapter(adapter: EmailAdapter) -> None:
    """Override the adapter — use in tests to inject TestEmailAdapter."""
    global _adapter
    _adapter = adapter
