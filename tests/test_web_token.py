"""Regressions for browser OAuth tokens rejected during client initialization."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.google_home.api import GlocaltokensApiClient
from custom_components.google_home.config_flow import GoogleHomeFlowHandler
from custom_components.google_home.const import CONF_MASTER_TOKEN, CONF_USERNAME


@pytest.mark.parametrize(
    "token", ["oauth2_4/synthetic", "1//synthetic", "aas_et/synthetic"]
)
def test_client_routes_token_to_real_library(token):
    """Exercise glocaltokens' real constructor validation without contacting Google."""
    client = GlocaltokensApiClient(
        hass=MagicMock(),
        session=MagicMock(),
        username="user@example.com",
        master_token=token,
    )
    if token.startswith("aas_et/"):
        assert client._client.master_token == token
        assert client._client.oauth_token is None
    else:
        assert client._client.master_token is None
        assert client._client.oauth_token == token


@pytest.mark.parametrize("token", ["oauth2_4/synthetic", "1//synthetic"])
@pytest.mark.asyncio
async def test_web_token_flow_reaches_exchange(token):
    """A web cookie reaches the exchange instead of raising before the try block."""
    flow = GoogleHomeFlowHandler()
    flow.hass = MagicMock()
    with (
        patch.object(flow, "_async_probe_addon", AsyncMock(return_value=(None, None))),
        patch("custom_components.google_home.config_flow.async_get_clientsession"),
        patch.object(
            GlocaltokensApiClient,
            "exchange_web_token",
            AsyncMock(return_value="aas_et/exchanged"),
        ) as exchange,
        patch.object(GlocaltokensApiClient, "get_access_token", AsyncMock()) as access,
        patch.object(
            flow, "async_step_mode", AsyncMock(return_value={"step_id": "mode"})
        ),
    ):
        result = await flow.async_step_token(
            {CONF_USERNAME: "user@example.com", CONF_MASTER_TOKEN: token}
        )
    exchange.assert_awaited_once_with(token)
    access.assert_awaited_once()
    assert flow._master_token == "aas_et/exchanged"
    assert result == {"step_id": "mode"}
