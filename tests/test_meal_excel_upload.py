"""Tests for archiving Excel uploads independently from their analysis."""

import hashlib
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
from app.schemas.users import AdminUserSchema
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


@pytest.mark.asyncio
async def test_admin_can_download_archived_original(
    meal_upload_api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The archived original is returned as-is with its upload filename."""
    monkeypatch.setattr(meals_router.Config, "MEAL_UPLOAD_ARCHIVE_DIR", tmp_path)
    _write_upload_sidecar(tmp_path, "식단표", "2026-09-21T08:00:00+09:00")

    response = await meal_upload_api.get("/meals/excel/uploads/식단표/file")
    assert response.status_code == 200
    assert response.content == b"workbook"
    assert "spreadsheetml" in response.headers["content-type"]
    assert "attachment" in response.headers["content-disposition"]

    missing = await meal_upload_api.get("/meals/excel/uploads/nope/file")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_download_rejects_non_admin(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A caller without global_admin or meal_admin gets 403, not the file."""
    import app.utils.db as db_utils  # noqa: PLC0415

    monkeypatch.setattr(meals_router.Config, "MEAL_UPLOAD_ARCHIVE_DIR", tmp_path)
    _write_upload_sidecar(tmp_path, "secret", "2026-09-21T08:00:00+09:00")
    user = await db.scalar(select(User).where(User.user_id == "test-user"))
    assert user is not None

    async def current_user(_db: AsyncSession, _user_id: str) -> User:
        return user

    async def not_admin(_user: User) -> AdminUserSchema:
        return AdminUserSchema(
            id=user.id,
            user_id=user.user_id,
            created_at=user.created_at,
            global_admin=False,
            meal_admin=False,
        )

    monkeypatch.setattr(db_utils, "get_current_user", current_user)
    monkeypatch.setattr(db_utils, "check_admin_user", not_admin)

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db

    app = FastAPI()
    app.include_router(meals_router.router)
    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            "/meals/excel/uploads/secret/file", headers={"X-User-ID": "test-user"}
        )
    assert response.status_code == 403
    assert response.content != b"workbook"


@pytest.mark.asyncio
async def test_download_finds_upload_id_with_surrounding_spaces(
    meal_upload_api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Whitespace around the id is stripped like the sync selection rule."""
    monkeypatch.setattr(meals_router.Config, "MEAL_UPLOAD_ARCHIVE_DIR", tmp_path)
    _write_upload_sidecar(tmp_path, "abc", "2026-09-21T08:00:00+09:00")

    response = await meal_upload_api.get("/meals/excel/uploads/%20abc%20/file")
    assert response.status_code == 200
    assert response.content == b"workbook"


@pytest.mark.asyncio
async def test_download_returns_404_when_upload_lacks_original_file(
    meal_upload_api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An upload without original.xlsx is dropped from the list, so it is 404."""
    monkeypatch.setattr(meals_router.Config, "MEAL_UPLOAD_ARCHIVE_DIR", tmp_path)
    _write_upload_sidecar(tmp_path, "gone", "2026-09-21T08:00:00+09:00")
    next(tmp_path.rglob("original.xlsx")).unlink()

    response = await meal_upload_api.get("/meals/excel/uploads/gone/file")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_download_encodes_korean_filename_in_content_disposition(
    meal_upload_api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Non-ASCII file names use RFC 5987 percent-encoding."""
    monkeypatch.setattr(meals_router.Config, "MEAL_UPLOAD_ARCHIVE_DIR", tmp_path)
    _write_upload_sidecar(tmp_path, "식단표", "2026-09-21T08:00:00+09:00")

    response = await meal_upload_api.get("/meals/excel/uploads/식단표/file")
    disposition = response.headers["content-disposition"]
    assert "filename*=utf-8''" in disposition
    assert "%EC%8B%9D%EB%8B%A8%ED%91%9C.xlsx" in disposition


@pytest.mark.asyncio
async def test_download_requires_user_id_header(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Without X-User-ID the real dependency answers 401."""
    monkeypatch.setattr(meals_router.Config, "MEAL_UPLOAD_ARCHIVE_DIR", tmp_path)
    _write_upload_sidecar(tmp_path, "secret", "2026-09-21T08:00:00+09:00")

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db

    app = FastAPI()
    app.include_router(meals_router.router)
    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/meals/excel/uploads/secret/file")
    assert response.status_code == 401
    assert response.content != b"workbook"


@pytest.mark.asyncio
async def test_download_blank_id_returns_404_not_latest(
    meal_upload_api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A whitespace-only id must not fall back to the latest upload."""
    monkeypatch.setattr(meals_router.Config, "MEAL_UPLOAD_ARCHIVE_DIR", tmp_path)
    _write_upload_sidecar(tmp_path, "old", "2026-09-20T08:00:00+09:00")
    _write_upload_sidecar(tmp_path, "new", "2026-09-21T08:00:00+09:00")

    response = await meal_upload_api.get("/meals/excel/uploads/%20/file")
    assert response.status_code == 404


def _write_custom_upload(
    root: Path,
    folder: str,
    record: object,
    content: bytes = b"workbook",
    *,
    year: str = "2026",
) -> Path:
    """Write an archive folder with an arbitrary result.json payload."""
    archive_dir = root / year / "09" / folder
    archive_dir.mkdir(parents=True)
    (archive_dir / "original.xlsx").write_bytes(content)
    text = record if isinstance(record, str) else json.dumps(record)
    (archive_dir / "result.json").write_text(text, encoding="utf-8")
    return archive_dir


def _record(upload_id: str, **extra: object) -> dict[str, object]:
    """Build a minimal valid result record."""
    return {
        "upload_id": upload_id,
        "file_name": f"{upload_id}.xlsx",
        "uploaded_at": "2026-09-21T08:00:00+09:00",
        **extra,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_id",
    [
        "..%2F..%2Fx",
        "%2e%2e",
        "2026",
        "09",
        "real-upl",
        "pload",
        "a" * 5000,
        "%09",
        "%20%20",
        "%0A",
    ],
)
async def test_download_rejects_unknown_or_malformed_ids(
    meal_upload_api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    bad_id: str,
) -> None:
    """Path tricks, partial ids and blank ids never serve any file."""
    monkeypatch.setattr(meals_router.Config, "MEAL_UPLOAD_ARCHIVE_DIR", tmp_path)
    _write_custom_upload(tmp_path, "real-upload", _record("real-upload"), b"SECRET")

    response = await meal_upload_api.get(f"/meals/excel/uploads/{bad_id}/file")
    assert response.status_code == 404
    assert b"SECRET" not in response.content


@pytest.mark.asyncio
async def test_download_skips_broken_and_non_dict_records(
    meal_upload_api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Corrupt sidecars do not break downloading of healthy uploads."""
    monkeypatch.setattr(meals_router.Config, "MEAL_UPLOAD_ARCHIVE_DIR", tmp_path)
    _write_custom_upload(tmp_path, "broken", "{not json")
    _write_custom_upload(tmp_path, "listy", ["upload_id", "x"])
    _write_custom_upload(tmp_path, "noid", {"file_name": "x.xlsx"})
    _write_custom_upload(tmp_path, "good", _record("good"), b"good-bytes")

    response = await meal_upload_api.get("/meals/excel/uploads/good/file")
    assert response.status_code == 200
    assert response.content == b"good-bytes"


@pytest.mark.asyncio
async def test_download_duplicate_upload_id_serves_newest_matching_pair(
    meal_upload_api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """With a duplicated id the newest record wins, with its own original."""
    monkeypatch.setattr(meals_router.Config, "MEAL_UPLOAD_ARCHIVE_DIR", tmp_path)
    old = _record("dup", uploaded_at="2026-09-20T08:00:00+09:00")
    new = _record("dup", uploaded_at="2026-09-22T08:00:00+09:00")
    _write_custom_upload(tmp_path, "dup", old, b"OLD", year="2025")
    _write_custom_upload(tmp_path, "dup", new, b"NEW")

    response = await meal_upload_api.get("/meals/excel/uploads/dup/file")
    assert response.status_code == 200
    assert response.content == b"NEW"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("file_name", "expected"),
    [
        ("식단표.xlsx", "filename*=utf-8''%EC%8B%9D%EB%8B%A8%ED%91%9C.xlsx"),
        ("my menu.xlsx", "filename*=utf-8''my%20menu.xlsx"),
        ('we"ird.xlsx', "filename*=utf-8''we%22ird.xlsx"),
        ("../../etc/passwd.xlsx", 'filename="passwd.xlsx"'),
        ("C:\\dir\\sheet.xlsx", 'filename="sheet.xlsx"'),
        ("UPPER.XLSX", 'filename="UPPER.XLSX"'),
        (
            "evil\r\nX-Injected: 1.xlsx",
            "filename*=utf-8''evilX-Injected%3A%201.xlsx",
        ),
        ("", 'filename="menu.xlsx"'),
        (None, 'filename="menu.xlsx"'),
    ],
)
async def test_download_content_disposition_is_safe(
    meal_upload_api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    file_name: str | None,
    expected: str,
) -> None:
    """File names are sanitised and cannot inject headers or paths."""
    monkeypatch.setattr(meals_router.Config, "MEAL_UPLOAD_ARCHIVE_DIR", tmp_path)
    record = _record("fn")
    record["file_name"] = file_name
    _write_custom_upload(tmp_path, "fn", record)

    response = await meal_upload_api.get("/meals/excel/uploads/fn/file")
    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment")
    assert "\r" not in disposition and "\n" not in disposition
    assert "x-injected" not in response.headers
    assert "/" not in disposition.split("filename", maxsplit=1)[1]
    assert expected in disposition, disposition


@pytest.mark.asyncio
async def test_download_body_and_media_type_match_original(
    meal_upload_api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Binary content is returned byte for byte with the xlsx media type."""
    monkeypatch.setattr(meals_router.Config, "MEAL_UPLOAD_ARCHIVE_DIR", tmp_path)
    payload = bytes(range(256)) * 64
    _write_custom_upload(tmp_path, "bin", _record("bin"), payload)

    response = await meal_upload_api.get("/meals/excel/uploads/bin/file")
    assert response.status_code == 200
    assert hashlib.sha256(response.content).hexdigest() == (
        hashlib.sha256(payload).hexdigest()
    )
    assert response.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("analysis_status", ["failed", "pending", "completed"])
async def test_download_works_regardless_of_analysis_status(
    meal_upload_api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    analysis_status: str,
) -> None:
    """The archived original is downloadable whatever the analysis outcome."""
    monkeypatch.setattr(meals_router.Config, "MEAL_UPLOAD_ARCHIVE_DIR", tmp_path)
    record = _record("an", analysis_status=analysis_status, status="uploaded")
    _write_custom_upload(tmp_path, "an", record, b"orig")

    response = await meal_upload_api.get("/meals/excel/uploads/an/file")
    assert response.status_code == 200
    assert response.content == b"orig"
