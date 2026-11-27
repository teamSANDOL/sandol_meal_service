"""Keycloak 장애 시에도 기동이 막히지 않는지 검증합니다."""

from __future__ import annotations

import pytest
import main
from fastapi.testclient import TestClient

from app.config import Config
from app.models.restaurants import (
    ServiceAccountNotReadyError,
    _service_state,
    get_service_user_id,
)
from app.utils import lifespan as lf


async def _no_sleep(_delay: float) -> None:
    return None


pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "SERVICE_ACCOUNT_SUB", "sa-sub")
    monkeypatch.setitem(lf.readiness, "service_account", False)


async def test_healthy_path_single_call(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    async def ok() -> None:
        calls.append(1)

    monkeypatch.setattr(lf, "ensure_service_account_in_db", ok)
    assert await lf.ensure_service_account_resilient(_no_sleep) is True
    assert calls == [1]
    assert lf.readiness["service_account"] is True


async def test_transient_failure_then_success(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = {"n": 0}

    async def flaky() -> None:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ConnectionError("keycloak down")

    monkeypatch.setattr(lf, "ensure_service_account_in_db", flaky)
    assert await lf.ensure_service_account_resilient(_no_sleep) is True
    assert attempts["n"] == 3


async def test_gives_up_then_background_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {"up": False, "restaurants": 0}

    async def kc() -> None:
        if not state["up"]:
            raise ConnectionError("keycloak down")

    async def restaurants() -> None:
        state["restaurants"] += 1

    monkeypatch.setattr(lf, "ensure_service_account_in_db", kc)
    monkeypatch.setattr(lf, "sync_restaurants", restaurants)
    monkeypatch.setattr(lf, "STARTUP_RETRY_TOTAL_LIMIT", 0.0)

    assert await lf.ensure_service_account_resilient(_no_sleep) is False
    assert lf.readiness["service_account"] is False

    sleeps = {"n": 0}

    async def sleep_then_recover(_delay: float) -> None:
        sleeps["n"] += 1
        if sleeps["n"] == 3:
            state["up"] = True

    await lf.complete_deferred_startup(sleep_then_recover)
    assert lf.readiness["service_account"] is True
    assert state["restaurants"] == 1


async def test_missing_sub_still_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "SERVICE_ACCOUNT_SUB", None)
    with pytest.raises(RuntimeError):
        await lf.ensure_service_account_resilient(_no_sleep)


async def test_service_user_id_not_ready_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(_service_state, "user_id", None)
    with pytest.raises(ServiceAccountNotReadyError):
        get_service_user_id()

    @main.app.get("/_probe_not_ready")
    async def probe() -> None:
        get_service_user_id()

    client = TestClient(main.app, raise_server_exceptions=False)
    assert client.get("/_probe_not_ready").status_code == 503
    assert client.get("/health").json()["status"] == "ok"
