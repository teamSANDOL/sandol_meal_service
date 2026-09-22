"""Tests for archiving Excel uploads independently from their analysis."""

import json
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.routers.meals as meals_router
from app.models.meals import Meal
from app.models.user import User
from app.services.excel_importer import ParsedMeal
from app.utils.db import get_admin_user, get_current_user, get_db


@pytest_asyncio.fixture
async def meal_upload_api(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create an upload API client with the test user and database."""
    app = FastAPI()
    app.include_router(meals_router.router)

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db

    async def override_current_user() -> User:
        user = await db.scalar(select(User).where(User.user_id == "test-user"))
        assert user is not None
        return user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_admin_user] = override_current_user

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_stage",
    ["empty_parse", "parser_exception", "invalid_archive"],
)
async def test_analysis_failure_still_returns_archived_upload_success(
    meal_upload_api: AsyncClient,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure_stage: str,
) -> None:
    """A stored workbook is successful even when the parser finds no meals."""

    class EmptyParser:
        """Simulate a valid workbook whose menu structure is not recognized."""

        def __init__(self, _path: str) -> None:
            pass

        def parse(self, *, today: object) -> list[object]:
            _ = today
            if failure_stage == "parser_exception":
                raise ValueError("unrecognized menu structure")
            return []

    def validate_archive(_contents: bytes) -> None:
        if failure_stage == "invalid_archive":
            raise ValueError("invalid XLSX archive")

    monkeypatch.setattr(meals_router.Config, "MEAL_UPLOAD_ARCHIVE_DIR", tmp_path)
    monkeypatch.setattr(meals_router.Config, "TMP_DIR", tmp_path)
    monkeypatch.setattr(meals_router, "_validate_xlsx_archive", validate_archive)
    monkeypatch.setattr(meals_router, "ExcelMealImporter", EmptyParser)
    original = b"original workbook bytes"

    response = await meal_upload_api.post(
        "/meals/excel",
        files={
            "file": (
                "weekly-menu.xlsx",
                original,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["upload_status"] == "completed"
    assert data["analysis_status"] == "failed"
    assert data["status"] == "uploaded"
    assert "summary" not in data

    original_path = next(tmp_path.rglob("original.xlsx"))
    assert original_path.read_bytes() == original
    result_path = original_path.with_name("result.json")
    stored_result = json.loads(result_path.read_text(encoding="utf-8"))
    assert stored_result["upload_status"] == "completed"
    assert stored_result["analysis_status"] == "failed"

    meals = (await db.scalars(select(Meal))).all()
    assert meals == []


def _write_upload_sidecar(root: Path, upload_id: str, uploaded_at: str) -> None:
    """Create a minimal archived workbook record for API tests."""
    archive_dir = root / "2026" / "09" / upload_id
    archive_dir.mkdir(parents=True)
    (archive_dir / "original.xlsx").write_bytes(b"workbook")
    (archive_dir / "result.json").write_text(
        json.dumps(
            {
                "upload_id": upload_id,
                "status": "uploaded",
                "upload_status": "completed",
                "analysis_status": "failed",
                "file_name": f"{upload_id}.xlsx",
                "file_size": 8,
                "sha256": upload_id,
                "uploaded_at": uploaded_at,
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_admin_can_list_uploads_and_sync_latest_or_selected_file(
    meal_upload_api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The list is newest-first and sync defaults to latest but accepts an ID."""
    monkeypatch.setattr(meals_router.Config, "MEAL_UPLOAD_ARCHIVE_DIR", tmp_path)
    monkeypatch.setattr(meals_router.Config, "TMP_DIR", tmp_path)
    _write_upload_sidecar(tmp_path, "older", "2026-09-20T08:00:00+09:00")
    _write_upload_sidecar(tmp_path, "latest", "2026-09-21T08:00:00+09:00")
    monkeypatch.setattr(meals_router, "_validate_xlsx_archive", lambda _contents: None)

    class FakeImporter:
        """Return one deterministic parsed meal without touching a workbook parser."""

        def __init__(self, _path: str) -> None:
            pass

        def parse(self, *, today: object) -> list[ParsedMeal]:
            _ = today
            return [ParsedMeal(1, "lunch", __import__("datetime").date(2026, 9, 21), ["메뉴"])]

        async def insert_parsed_to_db(
            self, _db: AsyncSession, _parsed: list[ParsedMeal]
        ) -> None:
            return None

    monkeypatch.setattr(meals_router, "ExcelMealImporter", FakeImporter)

    listed = await meal_upload_api.get("/meals/excel/uploads")
    assert listed.status_code == 200
    assert [item["upload_id"] for item in listed.json()["data"]] == [
        "latest",
        "older",
    ]
    assert listed.json()["data"][0]["is_latest"] is True

    latest_sync = await meal_upload_api.post("/meals/excel/sync", json={})
    assert latest_sync.status_code == 200
    assert latest_sync.json()["data"]["upload_id"] == "latest"
    assert latest_sync.json()["data"]["sync_status"] == "completed"

    selected_sync = await meal_upload_api.post(
        "/meals/excel/sync", json={"upload_id": "older"}
    )
    assert selected_sync.status_code == 200
    assert selected_sync.json()["data"]["upload_id"] == "older"
    assert selected_sync.json()["data"]["sync_source"] == "selected"


@pytest.mark.asyncio
async def test_admin_sync_returns_detailed_parse_failure(
    meal_upload_api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A malformed archived workbook returns a structured reason, not a blank 500."""
    monkeypatch.setattr(meals_router.Config, "MEAL_UPLOAD_ARCHIVE_DIR", tmp_path)
    monkeypatch.setattr(meals_router.Config, "TMP_DIR", tmp_path)
    _write_upload_sidecar(tmp_path, "broken", "2026-09-21T08:00:00+09:00")

    response = await meal_upload_api.post(
        "/meals/excel/sync",
        json={"upload_id": "broken"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["sync_status"] == "failed"
    assert data["sync_error_code"] == "invalid_workbook"
    assert "올바른 XLSX 구조" in data["sync_error_message"]
