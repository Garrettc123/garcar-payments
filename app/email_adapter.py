from __future__ import annotations

from abc import ABC, abstractmethod
from html import escape
from typing import Optional


class EmailAdapter(ABC):
    @abstractmethod
    def send_download_link(
        self,
        to: str,
        product_name: str,
        download_url: str,
        expires_in_hours: int = 24,
    ) -> str:
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
    ) -> str:
        html = (
            f"<p>Thank you for your purchase of <strong>{escape(product_name)}</strong>.</p>"
            f"<p><a href='{escape(download_url, quote=True)}'>Download your file</a></p>"
            f"<p>This link expires in {expires_in_hours} hour(s).</p>"
            f"<p>— Garcar Enterprise</p>"
        )
        response = self._resend.Emails.send(
            {
                "from": self._from,
                "to": to,
                "subject": f"Your {product_name} download link",
                "html": html,
            }
        )

        message_id = response.get("id") if isinstance(response, dict) else None
        if not isinstance(message_id, str) or not message_id.strip():
            raise RuntimeError("Email acceptance unconfirmed by provider")
        return message_id


# Module-level singleton — replaced by tests via ``set_email_adapter``
_adapter: Optional[EmailAdapter] = None


def get_email_adapter() -> EmailAdapter:
    global _adapter
    if _adapter is None:
        from app.settings import get_settings  # noqa: PLC0415

        s = get_settings()
        _adapter = ResendEmailAdapter(s.resend_api_key, s.email_from)
    return _adapter


def set_email_adapter(adapter: EmailAdapter) -> None:
    """Override the adapter — use in tests to inject TestEmailAdapter."""
    global _adapter
    _adapter = adapter
