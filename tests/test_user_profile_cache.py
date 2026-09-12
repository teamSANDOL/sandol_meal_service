"""Tests for the Keycloak user-profile cache."""

from collections.abc import Callable
from typing import Any, cast

import pytest
from cachetools import TTLCache
from keycloak import KeycloakGetError

from app.services import user_service


class FakeKeycloakAdmin:
    """Configurable async Keycloak client test double."""

    def __init__(self, response: object | Callable[[str], object]) -> None:
        self.calls = 0
        self._response = response

    async def a_get_user(self, *, user_id: str) -> dict[str, Any]:
        """Return the configured response or raise the configured exception."""
        self.calls += 1
        response = (
            self._response(user_id) if callable(self._response) else self._response
        )
        if isinstance(response, Exception):
            raise response
        return cast(dict[str, Any], response)


def _valid_user(user_id: str, *, username: str = "sandol") -> dict[str, object]:
    """Build a minimally complete Keycloak user response."""
    return {"id": user_id, "username": username}


@pytest.fixture(autouse=True)
def clear_profile_cache() -> None:
    """Keep module-level cache state isolated between tests."""
    user_service._PROFILE_CACHE.clear()


@pytest.mark.asyncio
async def test_successful_profile_is_cached_and_returned_as_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A validated profile uses one Keycloak request and cannot be mutated externally."""
    admin = FakeKeycloakAdmin(_valid_user("user-1"))
    monkeypatch.setattr(user_service, "get_local_keycloak_admin_client", lambda: admin)

    first = await user_service.get_cached_user_profile("user-1")
    first["display_name"] = "mutated"
    second = await user_service.get_cached_user_profile("user-1")

    assert admin.calls == 1
    assert second["display_name"] == "sandol"
    assert first is not second


@pytest.mark.asyncio
async def test_profile_cache_expires_after_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    """An expired profile is fetched again rather than served from cache."""
    now = [0.0]
    monkeypatch.setattr(
        user_service,
        "_PROFILE_CACHE",
        TTLCache(maxsize=1024, ttl=300, timer=lambda: now[0]),
    )
    admin = FakeKeycloakAdmin(_valid_user("user-1", username="first"))
    monkeypatch.setattr(user_service, "get_local_keycloak_admin_client", lambda: admin)

    assert (await user_service.get_cached_user_profile("user-1"))[
        "display_name"
    ] == "first"
    now[0] = 301.0
    admin._response = _valid_user("user-1", username="second")

    assert (await user_service.get_cached_user_profile("user-1"))[
        "display_name"
    ] == "second"
    assert admin.calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "raises"),
    [
        (KeycloakGetError("unavailable", response_code=503), False),
        ({"id": "different-user"}, False),
        (RuntimeError("unexpected"), True),
    ],
    ids=["keycloak-failure", "incomplete-response", "unexpected-error"],
)
async def test_failed_or_incomplete_profiles_are_not_cached(
    monkeypatch: pytest.MonkeyPatch,
    response: object,
    *,
    raises: bool,
) -> None:
    """Fallbacks and exceptions are retried instead of stored in the cache."""
    admin = FakeKeycloakAdmin(response)
    monkeypatch.setattr(user_service, "get_local_keycloak_admin_client", lambda: admin)

    if raises:
        with pytest.raises(RuntimeError, match="unexpected"):
            await user_service.get_cached_user_profile("user-1")
    else:
        profile = await user_service.get_cached_user_profile("user-1")
        assert profile["display_name"] == "user-1"

    assert "user-1" not in user_service._PROFILE_CACHE
    assert admin.calls == 1


@pytest.mark.asyncio
async def test_profile_cache_evicts_least_recently_used_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cache is bounded to 1,024 entries and evicts instead of clearing all data."""
    admin = FakeKeycloakAdmin(lambda user_id: _valid_user(user_id))
    monkeypatch.setattr(user_service, "get_local_keycloak_admin_client", lambda: admin)

    for index in range(1025):
        await user_service.get_cached_user_profile(f"user-{index}")

    assert user_service._PROFILE_CACHE.maxsize == 1024
    assert len(user_service._PROFILE_CACHE) == 1024
    assert "user-0" not in user_service._PROFILE_CACHE
    assert "user-1024" in user_service._PROFILE_CACHE
