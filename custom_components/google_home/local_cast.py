"""Read receiver volume directly over the device's local Cast socket."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from threading import Event
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pychromecast import Chromecast
from pychromecast.const import CAST_TYPE_CHROMECAST, CAST_TYPES
from pychromecast.controllers import BaseController
from pychromecast.controllers.receiver import NS_RECEIVER, TYPE_RECEIVER_STATUS
from pychromecast.error import PyChromecastError
from pychromecast.models import CastInfo, HostServiceInfo

from .volume import volume_percentage

if TYPE_CHECKING:
    from pychromecast.generated.cast_channel_pb2 import CastMessage

_LOGGER = logging.getLogger(__name__)
_SOCKET_TIMEOUT = 3.0
_STATUS_TIMEOUT = 5.0


class _VolumeStatusController(BaseController):
    """Require an explicit volume level instead of PyChromecast's default of 1.0."""

    def __init__(self) -> None:
        super().__init__(NS_RECEIVER, target_platform=True)
        self.ready = Event()
        self.volume: float | None = None

    def receive_message(self, _message: CastMessage, data: dict[str, Any]) -> bool:
        """Read only the receiver's actual volume field."""
        if data.get("type") != TYPE_RECEIVER_STATUS:
            return False
        status = data.get("status")
        volume = status.get("volume") if isinstance(status, Mapping) else None
        if isinstance(volume, Mapping):
            self.volume = volume_percentage(volume.get("level"), normalized=True)
        self.ready.set()
        return True


def read_cast_volume(host: str, cast_uuid: str, model: str, name: str) -> float | None:
    """Perform a bounded, read-only poll; the caller must use an executor.

    This owns a short-lived socket, not a Home Assistant Cast entity. No app is
    launched and no volume command is sent. Supplying device metadata also avoids
    PyChromecast performing additional HTTP discovery during construction.
    """
    try:
        identity = UUID(cast_uuid.removeprefix("uuid:"))
    except ValueError:
        _LOGGER.debug("Cannot read local Cast volume for %s: invalid Cast UUID", name)
        return None

    cast_type, manufacturer = CAST_TYPES.get(
        model.lower(), (CAST_TYPE_CHROMECAST, None)
    )
    info = CastInfo(
        services={HostServiceInfo(host, 8009)},
        uuid=identity,
        model_name=model,
        friendly_name=name,
        host=host,
        port=8009,
        cast_type=cast_type,
        manufacturer=manufacturer,
    )
    connection: Chromecast | None = None
    try:
        connection = Chromecast(info, tries=1, timeout=_SOCKET_TIMEOUT, retry_wait=0)
        reader = _VolumeStatusController()
        connection.register_handler(reader)
        connection.start()
        if not reader.ready.wait(timeout=_STATUS_TIMEOUT):
            _LOGGER.debug("Local Cast volume status timed out for %s", name)
            return None
        return reader.volume
    except (PyChromecastError, OSError, TimeoutError) as err:
        _LOGGER.debug("Local Cast volume read failed for %s: %s", name, err)
        return None
    finally:
        if connection is not None:
            try:
                connection.disconnect(timeout=_STATUS_TIMEOUT)
            except (PyChromecastError, OSError, TimeoutError, RuntimeError) as err:
                _LOGGER.debug(
                    "Local Cast volume socket cleanup failed for %s: %s", name, err
                )
