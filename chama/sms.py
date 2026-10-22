"""SMS delivery: Africa's Talking when configured, otherwise an in-memory outbox."""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

from .phone import mask

log = logging.getLogger(__name__)


class SmsGateway(Protocol):
    def send(self, to: str, message: str) -> bool: ...


@dataclass
class ConsoleGateway:
    outbox: list[tuple[str, str]] = field(default_factory=list)

    def send(self, to: str, message: str) -> bool:
        self.outbox.append((to, message))
        log.info("SMS to %s: %s", mask(to), message)
        return True


@dataclass
class AfricasTalkingGateway:
    username: str
    api_key: str
    sender_id: str | None = None
    sandbox: bool = False
    timeout: float = 10.0

    @property
    def url(self) -> str:
        host = "api.sandbox.africastalking.com" if self.sandbox else "api.africastalking.com"
        return f"https://{host}/version1/messaging"

    def send(self, to: str, message: str) -> bool:
        payload = {"username": self.username, "to": to, "message": message}
        if self.sender_id:
            payload["from"] = self.sender_id
        request = urllib.request.Request(
            self.url,
            data=urllib.parse.urlencode(payload).encode(),
            headers={"apiKey": self.api_key, "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read() or b"{}")
        except (OSError, ValueError) as exc:
            log.warning("SMS to %s failed: %s", mask(to), exc)
            return False
        recipients = body.get("SMSMessageData", {}).get("Recipients", [])
        return any(r.get("status") == "Success" for r in recipients)


def from_env() -> SmsGateway:
    username, api_key = os.getenv("AT_USERNAME"), os.getenv("AT_API_KEY")
    if username and api_key:
        return AfricasTalkingGateway(username, api_key, os.getenv("AT_SENDER_ID") or None, sandbox=username == "sandbox")
    return ConsoleGateway()
