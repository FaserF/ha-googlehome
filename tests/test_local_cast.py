"""Direct local receiver reads without HA Cast entities or Google credentials."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from pychromecast.error import ChromecastConnectionError

from custom_components.google_home.local_cast import read_cast_volume

CAST_UUID = "11111111222233334444555555555555"


def connection_with_payload(payload):
    """Deliver raw receiver data through the handler registered by our reader."""
    connection = MagicMock()
    # PyChromecast defaults this to 100% if the payload omits volume. Ignore it.
    connection.status = SimpleNamespace(volume_level=1.0)

    def start():
        controller = connection.register_handler.call_args.args[0]
        controller.receive_message(None, payload)

    connection.start.side_effect = start
    return connection


@pytest.mark.parametrize("level,expected", [(0, 0), (0.01, 1), (0.56, 56), (1, 100)])
def test_direct_receiver_volume_and_socket_cleanup(level, expected):
    connection = connection_with_payload(
        {"type": "RECEIVER_STATUS", "status": {"volume": {"level": level}}}
    )
    with patch(
        "custom_components.google_home.local_cast.Chromecast", return_value=connection
    ) as factory:
        assert (
            read_cast_volume("192.0.2.10", CAST_UUID, "Nest Hub", "Office") == expected
        )
    info = factory.call_args.args[0]
    assert info.host == "192.0.2.10"
    assert info.port == 8009
    assert info.uuid == UUID(CAST_UUID)
    assert info.cast_type is not None
    assert factory.call_args.kwargs["tries"] == 1
    assert factory.call_args.kwargs["timeout"] == 3
    connection.start.assert_called_once()
    connection.disconnect.assert_called_once_with(timeout=5)
    connection.start_app.assert_not_called()
    connection.set_volume.assert_not_called()


@pytest.mark.parametrize(
    "status",
    [
        None,
        {},
        {"volume": {}},
        {"volume": {"level": None}},
        {"volume": {"level": True}},
        {"volume": {"level": 1.5}},
    ],
)
def test_missing_or_invalid_receiver_volume_is_not_reported_as_zero(status):
    connection = connection_with_payload({"type": "RECEIVER_STATUS", "status": status})
    with patch(
        "custom_components.google_home.local_cast.Chromecast", return_value=connection
    ):
        assert read_cast_volume("192.0.2.10", CAST_UUID, "Nest Hub", "Office") is None
    connection.disconnect.assert_called_once()


def test_status_timeout_still_disconnects_the_worker():
    connection = MagicMock()
    ready = MagicMock()
    ready.wait.return_value = False
    with (
        patch("custom_components.google_home.local_cast.Event", return_value=ready),
        patch(
            "custom_components.google_home.local_cast.Chromecast",
            return_value=connection,
        ),
    ):
        assert read_cast_volume("192.0.2.10", CAST_UUID, "Nest Hub", "Office") is None
    connection.disconnect.assert_called_once_with(timeout=5)
    ready.wait.assert_called_once_with(timeout=5)


def test_connection_creation_failure_returns_no_volume():
    with patch(
        "custom_components.google_home.local_cast.Chromecast",
        side_effect=ChromecastConnectionError("unreachable"),
    ):
        assert read_cast_volume("192.0.2.10", CAST_UUID, "Nest Hub", "Office") is None


def test_disconnect_timeout_does_not_hide_the_received_volume(caplog):
    connection = connection_with_payload(
        {"type": "RECEIVER_STATUS", "status": {"volume": {"level": 0.56}}}
    )
    connection.disconnect.side_effect = TimeoutError("worker cleanup")
    with (
        patch(
            "custom_components.google_home.local_cast.Chromecast",
            return_value=connection,
        ),
        caplog.at_level("DEBUG", logger="custom_components.google_home.local_cast"),
    ):
        assert read_cast_volume("192.0.2.10", CAST_UUID, "Nest Hub", "Office") == 56
    assert "socket cleanup failed" in caplog.text


def test_invalid_identity_does_not_open_a_socket():
    with patch("custom_components.google_home.local_cast.Chromecast") as factory:
        assert (
            read_cast_volume("192.0.2.10", "not-a-uuid", "Nest Hub", "Office") is None
        )
    factory.assert_not_called()
