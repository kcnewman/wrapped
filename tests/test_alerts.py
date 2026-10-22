from unittest.mock import MagicMock, patch

import pytest
import requests

from wrapped.services.alerts import AlertDeliveryError, TelegramAlert


def test_telegram_alert_uses_plain_text_and_bounded_request():
    response = MagicMock()
    response.__enter__.return_value = response
    response.status_code = 200
    response.json.return_value = {"ok": True}
    with patch("wrapped.services.alerts.requests.post", return_value=response) as post:
        TelegramAlert("private-token", "private-chat")(
            "Job sync failed (run 7, RuntimeError)"
        )
    kwargs = post.call_args.kwargs
    assert kwargs["timeout"] == (3.05, 10)
    assert kwargs["allow_redirects"] is False
    assert kwargs["json"] == {
        "chat_id": "private-chat",
        "text": "Job sync failed (run 7, RuntimeError)",
    }


def test_alert_transport_error_has_static_message_and_no_chained_url():
    with (
        patch(
            "wrapped.services.alerts.requests.post",
            side_effect=requests.ConnectionError("https://bot/private-token"),
        ),
        pytest.raises(AlertDeliveryError) as raised,
    ):
        TelegramAlert("private-token", "private-chat")("Failed")
    assert "private-token" not in str(raised.value)
    assert raised.value.__suppress_context__ is True
