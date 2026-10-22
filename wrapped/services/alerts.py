"""Owner alerts are explicit job-runner calls, never logging handlers."""

from __future__ import annotations

import requests


class AlertDeliveryError(Exception):
    pass


class TelegramAlert:
    def __init__(self, token: str, chat_id: str) -> None:
        if not token or not chat_id:
            raise ValueError("Telegram owner alert configuration is incomplete")
        self._token = token
        self._chat_id = chat_id

    def __call__(self, message: str) -> None:
        try:
            with requests.post(
                f"https://api.telegram.org/bot{self._token}/sendMessage",
                json={"chat_id": self._chat_id, "text": message},
                timeout=(3.05, 10),
                allow_redirects=False,
            ) as response:
                if response.status_code != 200 or response.json().get("ok") is not True:
                    raise AlertDeliveryError("Owner alert was rejected")
        except (requests.RequestException, ValueError, AttributeError):
            raise AlertDeliveryError("Owner alert could not be delivered") from None
