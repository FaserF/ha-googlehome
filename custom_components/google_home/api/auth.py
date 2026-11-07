"""Authentication and token management mixin for Google Home API client."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from glocaltokens.client import GLocalAuthenticationTokens

from ..exceptions import (
    AdvancedProtectionActive,
    AuthenticationFailed,
    InvalidMasterToken,
    TwoFactorRequired,
)

if TYPE_CHECKING:
    import aiohttp
    from homeassistant.core import HomeAssistant

_LOGGER: logging.Logger = logging.getLogger(__package__)

# Patch glocaltokens get_master_token so get_access_token() doesn't fail when password is None (Token auth)
_orig_get_master_token = GLocalAuthenticationTokens.get_master_token


def _safe_get_master_token(self: GLocalAuthenticationTokens) -> str | None:
    """Return stored master_token if present, otherwise invoke original method."""
    if getattr(self, "master_token", None):
        return self.master_token
    return _orig_get_master_token(self)


GLocalAuthenticationTokens.get_master_token = _safe_get_master_token  # type: ignore[assignment,method-assign]


class AuthMixin:
    """Mixin handling Google Home Master Token and Access Token authentication."""

    hass: HomeAssistant
    _session: aiohttp.ClientSession
    username: str | None
    password: str | None
    master_token: str | None
    _client: GLocalAuthenticationTokens

    async def async_get_available_homes(self) -> dict[str, str]:
        """Fetch dictionary of available home_id -> home_name from HomeGraph."""

        def _get_homes() -> dict[str, str]:
            homes: dict[str, str] = {}
            try:
                hg = self._client.get_homegraph()
                if hg and hasattr(hg, "home") and hg.home:
                    hid = getattr(hg.home, "home_id", "") or "default_home"
                    hname = getattr(hg.home, "home_name", "") or "My Google Home"
                    homes[hid] = hname

                    # Dynamically scan raw protobuf payload for all StructureTrait definitions
                    raw = hg.SerializeToString()
                    import re

                    found_names: list[str] = []
                    for match in re.finditer(
                        rb"StructureTrait[^\x00-\x1F]*\x12[\x01-\x20]\n\x04name\x12[\x01-\x20]\x1a[\x01-\x20]([^\x00-\x1F]+)",
                        raw,
                    ):
                        struct_name = match.group(1).decode("utf-8", errors="ignore")
                        if struct_name not in found_names:
                            found_names.append(struct_name)

                    # Correlate any rooms that belong to other structure UUIDs
                    other_structure_ids: list[str] = []
                    for r in getattr(hg.home, "rooms", []):
                        rid = getattr(r, "room_id", "")
                        if "." in rid:
                            prefix_uuid = rid.split(".")[0]
                            if (
                                prefix_uuid != hid
                                and prefix_uuid not in other_structure_ids
                            ):
                                other_structure_ids.append(prefix_uuid)

                    other_names = [n for n in found_names if n != hname]
                    for idx, sid in enumerate(other_structure_ids):
                        if idx < len(other_names):
                            homes[sid] = other_names[idx]
                        elif len(other_names) == 1:
                            homes[sid] = other_names[0]
                        else:
                            homes[sid] = f"Zuhause ({sid[:8]})"

                    return homes
            except Exception as exc:
                _LOGGER.debug(
                    "Could not fetch available homes in local client: %s", exc
                )
            return homes

        return await self.hass.async_add_executor_job(_get_homes)

    async def get_master_token(self) -> str:
        """Get master token (short-circuit if already available, PR #1042)."""
        if self.master_token:
            return self.master_token

        def _get_master_token() -> str | None:
            if not self.username or not self.password:
                return None
            try:
                from gpsoauth import perform_master_login

                res = perform_master_login(
                    self.username,
                    self.password,
                    self._client.get_android_id(),
                )
                if "Token" in res:
                    self.master_token = res["Token"]
                    self._client.master_token = self.master_token
                    return self.master_token

                error_detail = res.get("Error", "").lower()
                error_url = res.get("Url", "").lower()
                _LOGGER.debug("Google auth response details: %s", res)

                if (
                    "advancedprotection" in error_detail
                    or "advancedprotection" in error_url
                    or "securesignin" in error_detail
                ):
                    raise AdvancedProtectionActive(
                        "Google Advanced Protection Program blocks password/app-password authentication."
                    )

                if (
                    "needsbrowser" in error_detail
                    or "secondfactor" in error_detail
                    or "badauthentication" in error_detail
                ):
                    raise TwoFactorRequired(
                        f"Google 2FA / App Password required ({res.get('Error')})"
                    )
            except (AuthenticationFailed, TwoFactorRequired, AdvancedProtectionActive):
                raise
            except Exception as err:
                _LOGGER.debug("Direct master login exception: %s", err)

            return self._client.get_master_token()

        try:
            master_token = await self.hass.async_add_executor_job(_get_master_token)
        except (TwoFactorRequired, AdvancedProtectionActive):
            raise
        except Exception as err:
            raise AuthenticationFailed(f"Failed to fetch master token: {err}") from err

        if master_token is None:
            raise TwoFactorRequired(
                "Could not obtain master token, App Password / 2FA required"
            )
        self.master_token = master_token
        return master_token

    async def exchange_web_token(self, oauth_token: str) -> str:
        """Exchange browser oauth_token (from accounts.google.com/EmbeddedSetup) for master token."""
        username = self.username
        if not username:
            raise AuthenticationFailed(
                "Email username is required to exchange web oauth token."
            )

        def _exchange() -> str | None:
            from gpsoauth import exchange_token

            res = exchange_token(
                username,
                oauth_token,
                self._client.get_android_id(),
            )
            _LOGGER.debug(
                "OAuth token exchange response: %s",
                {k: v for k, v in res.items() if k != "Token"},
            )
            if "Token" in res:
                return res["Token"]
            return None

        try:
            token = await self.hass.async_add_executor_job(_exchange)
        except Exception as err:
            raise AuthenticationFailed(
                f"Failed to exchange web oauth token: {err}"
            ) from err

        if not token:
            raise InvalidMasterToken("Google rejected the OAuth token exchange.")
        self.master_token = token
        self._client.master_token = token
        return token

    async def get_access_token(self) -> str:
        """Get Google access token using master token."""
        if not self.master_token:
            await self.get_master_token()

        def _get_access_token() -> str | None:
            return self._client.get_access_token()

        try:
            access_token = await self.hass.async_add_executor_job(_get_access_token)
        except Exception as err:
            raise AuthenticationFailed(f"Failed to fetch access token: {err}") from err

        if access_token is None:
            raise InvalidMasterToken("Could not obtain access token")
        return access_token
