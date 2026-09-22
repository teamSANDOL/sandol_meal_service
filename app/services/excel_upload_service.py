"""Workbook archive, analysis, and synchronization workflow."""

import datetime as dt
import hashlib
import io
import json
import shutil
import tempfile
import uuid
import zipfile
import zlib
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Config, logger
from app.services.crawler_service import _sync_lock
from app.services.excel_importer import (
    E_RESTAURANT_ID,
    TIP_RESTAURANT_ID,
    ExcelMealImporter,
    ParsedMeal,
)

_MAX_XLSX_ENTRIES = 2000
_MAX_XLSX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
_MAX_XLSX_COMPRESSION_RATIO = 100


class UploadAnalysisError(Exception):
    """Safe, user-facing reason for an archived workbook analysis failure."""

    def __init__(self, code: str, message: str) -> None:
        """Store a stable error code and a user-facing message."""
        self.code = code
        self.message = message
        super().__init__(message)


def validate_xlsx_archive(contents: bytes) -> None:
    """Reject corrupt or oversized ZIP payloads before opening them in pandas."""
    try:
        with zipfile.ZipFile(io.BytesIO(contents)) as workbook:
            entries = workbook.infolist()
            names = {entry.filename for entry in entries}
            uncompressed_size = sum(entry.file_size for entry in entries)
            if (
                len(entries) > _MAX_XLSX_ENTRIES
                or uncompressed_size > _MAX_XLSX_UNCOMPRESSED_BYTES
                or uncompressed_size > max(1, len(contents)) * _MAX_XLSX_COMPRESSION_RATIO
                or "[Content_Types].xml" not in names
                or "xl/workbook.xml" not in names
                or workbook.testzip() is not None
            ):
                raise ValueError("invalid_xlsx_archive")
    except (EOFError, OSError, RuntimeError, zipfile.BadZipFile, zlib.error) as exc:
        raise ValueError("invalid_xlsx_archive") from exc


def write_upload_result(path: Path, result: dict[str, Any]) -> None:
    """Atomically replace the result sidecar without exposing partial JSON."""
    temporary_path = path.with_suffix(".json.tmp")
    try:
        temporary_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def record_analysis_failure(
    result_path: Path,
    result: dict[str, Any],
    *,
    error_code: str,
    error_message: str | None = None,
) -> None:
    """Record analysis failure without reclassifying the archived upload."""
    result["status"] = "uploaded"
    result["analysis_status"] = "failed"
    result["analysis_error_code"] = error_code
    if error_message:
        result["analysis_error_message"] = error_message
    try:
        write_upload_result(result_path, result)
    except OSError:
        logger.exception("[excel_upload] 결과 sidecar 기록에 실패했습니다.")


def upload_records() -> list[tuple[Path, dict[str, Any]]]:
    """Read archived upload sidecars, newest upload first."""
    root = Config.MEAL_UPLOAD_ARCHIVE_DIR
    if not root.exists():
        return []
    records: list[tuple[Path, dict[str, Any]]] = []
    for result_path in root.glob("*/*/*/result.json"):
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(result, dict) and result.get("upload_id") and result_path.with_name(
            "original.xlsx"
        ).is_file():
            records.append((result_path, result))

    def sort_key(record: tuple[Path, dict[str, Any]]) -> dt.datetime:
        value = record[1].get("uploaded_at")
        if isinstance(value, str):
            try:
                parsed = dt.datetime.fromisoformat(value)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=Config.TZ)
            except ValueError:
                pass
        return dt.datetime.min.replace(tzinfo=Config.TZ)

    records.sort(key=sort_key, reverse=True)
    return records


def upload_record(upload_id: str | None) -> tuple[Path, dict[str, Any]] | None:
    """Resolve a selected upload, or the latest upload when omitted."""
    records = upload_records()
    if upload_id is None or not upload_id.strip():
        return records[0] if records else None
    return next((item for item in records if item[1].get("upload_id") == upload_id.strip()), None)


def record_sync_failure(
    result_path: Path,
    result: dict[str, Any],
    *,
    error_code: str,
    error_message: str,
    requested_at: str,
) -> dict[str, Any]:
    """Persist a detailed sync failure while retaining the original upload."""
    failure = {**result, "sync_status": "failed", "sync_error_code": error_code,
               "sync_error_message": error_message, "synced_at": requested_at}
    try:
        write_upload_result(result_path, failure)
    except OSError:
        logger.exception("[excel_sync] 동기화 실패 결과 기록에 실패했습니다.")
    return failure


def find_completed_upload(sha256: str) -> dict[str, Any] | None:
    """Return an earlier successful result for an identical workbook/parser."""
    for result_path in Config.MEAL_UPLOAD_ARCHIVE_DIR.glob("*/*/*/result.json"):
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(result, dict)
            and result.get("status") == "completed"
            and result.get("sha256") == sha256
            and result.get("parser_version") == Config.MEAL_UPLOAD_PARSER_VERSION
        ):
            return result
    return None


def build_upload_analysis(parsed: list[ParsedMeal], metadata: dict[str, Any]) -> dict[str, Any]:
    """Serialize the parser result into the upload API contract."""
    restaurant_names = {TIP_RESTAURANT_ID: "TIP 가가식당", E_RESTAURANT_ID: "E동 레스토랑"}
    meal_labels = {"breakfast": "조식", "brunch": "브런치", "lunch": "중식", "dinner": "석식"}
    ordered = sorted(parsed, key=lambda meal: (meal.date, meal.restaurant_id, meal.meal_type))
    return {
        **metadata, "status": "completed", "analysis_status": "completed",
        "period": {"start_date": min(meal.date for meal in ordered).isoformat(),
                    "end_date": max(meal.date for meal in ordered).isoformat()},
        "summary": {"parsed": len(ordered), "reflected": len(ordered),
                     "restaurants": len({meal.restaurant_id for meal in ordered})},
        "items": [{"restaurant_id": meal.restaurant_id,
                   "restaurant": restaurant_names.get(meal.restaurant_id, f"식당 {meal.restaurant_id}"),
                   "meal_type": meal.meal_type,
                   "meal_type_label": meal_labels.get(meal.meal_type, meal.meal_type),
                   "date": meal.date.isoformat(), "menu": meal.menu} for meal in ordered],
    }


def store_upload_original(archive_dir: Path, metadata: dict[str, Any], contents: bytes) -> Path:
    """Persist the original and initial processing sidecar before DB writes."""
    original_path = archive_dir / "original.xlsx"
    result_path = archive_dir / "result.json"
    try:
        Config.MEAL_UPLOAD_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(Config.MEAL_UPLOAD_ARCHIVE_DIR).free < len(contents) + 65536:
            raise OSError("archive_space_unavailable")
        archive_dir.mkdir(parents=True, exist_ok=False)
        original_path.write_bytes(contents)
        metadata["upload_status"] = "completed"
        write_upload_result(result_path, metadata)
    except OSError as exc:
        raise HTTPException(status_code=507, detail="원본 파일을 보관할 저장 공간이 부족합니다.") from exc
    return result_path


def load_parsed_workbook(
    contents: bytes,
    *,
    today: dt.date,
    importer_class: type[ExcelMealImporter] = ExcelMealImporter,
    archive_validator: Any = validate_xlsx_archive,
) -> tuple[ExcelMealImporter, list[ParsedMeal]]:
    """Validate and parse workbook bytes with a stable detailed error reason."""
    try:
        archive_validator(contents)
    except ValueError as exc:
        raise UploadAnalysisError("invalid_workbook", "파일이 올바른 XLSX 구조가 아닙니다. Excel에서 다시 저장한 뒤 시도해주세요.") from exc
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".xlsx", prefix="meal-upload-", dir=Config.TMP_DIR, delete=False) as file:
            temporary_path = Path(file.name)
            file.write(contents)
        importer = importer_class(str(temporary_path))
        parsed = importer.parse(today=today)
    except Exception as exc:
        reason = str(exc).strip()
        detail = "워크북 분석 중 오류가 발생했습니다."
        if reason:
            detail = f"{detail} ({type(exc).__name__}: {reason[:300]})"
        raise UploadAnalysisError("parser_error", detail) from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    if not parsed:
        raise UploadAnalysisError("no_menus", "날짜 헤더, TIP/E동 식당 블록 또는 메뉴 셀을 찾지 못했습니다.")
    return importer, parsed


def parse_upload_workbook(  # noqa: PLR0913
    contents: bytes,
    result_path: Path,
    metadata: dict[str, Any],
    today: dt.date,
    *,
    importer_class: type[ExcelMealImporter] = ExcelMealImporter,
    archive_validator: Any = validate_xlsx_archive,
) -> tuple[ExcelMealImporter | None, list[ParsedMeal]]:
    """Analyze a workbook while keeping analysis failure separate from upload."""
    try:
        return load_parsed_workbook(
            contents,
            today=today,
            importer_class=importer_class,
            archive_validator=archive_validator,
        )
    except UploadAnalysisError as exc:
        record_analysis_failure(result_path, metadata, error_code=exc.code, error_message=exc.message)
        logger.info("[excel_upload] 워크북 분석 실패: %s", exc.message)
        return None, []


async def apply_uploaded_meals(importer: ExcelMealImporter, parsed: list[ParsedMeal], db: AsyncSession, result_path: Path, metadata: dict[str, Any]) -> None:
    """Apply one parsed workbook transaction and retain any apply failure."""
    try:
        await importer.insert_parsed_to_db(db, parsed)
    except Exception as exc:
        await db.rollback()
        metadata.update({"status": "uploaded", "apply_status": "failed", "apply_error_code": "excel_apply_failed"})
        try:
            write_upload_result(result_path, metadata)
        except OSError:
            logger.exception("[excel_upload] 반영 실패 결과 기록에 실패했습니다.")
        raise HTTPException(status_code=500, detail="원본 파일은 업로드됐지만 메뉴 반영에 실패했습니다. 기존 메뉴는 변경되지 않았습니다.") from exc


async def upload_workbook(  # noqa: PLR0913
    contents: bytes,
    *,
    file_name: str,
    uploaded_by: str,
    db: AsyncSession,
    importer_class: type[ExcelMealImporter] = ExcelMealImporter,
    archive_validator: Any = validate_xlsx_archive,
) -> tuple[dict[str, Any], bool]:
    """Archive, analyze, and immediately apply one workbook."""
    if not file_name.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail=".xlsx 파일만 업로드할 수 있습니다.")
    if len(contents) > Config.MEAL_UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=413, detail="파일 크기는 10MB 이하여야 합니다.")
    if not contents:
        raise HTTPException(status_code=400, detail="빈 파일은 업로드할 수 없습니다.")

    duplicate = find_completed_upload(hashlib.sha256(contents).hexdigest())
    if duplicate is not None:
        return {"data": {**duplicate, "already_applied": True}}, True

    uploaded_at = dt.datetime.now(tz=Config.TZ)
    upload_id = str(uuid.uuid4())
    metadata: dict[str, Any] = {
        "upload_id": upload_id,
        "status": "processing",
        "analysis_status": "pending",
        "file_name": file_name,
        "file_size": len(contents),
        "sha256": hashlib.sha256(contents).hexdigest(),
        "parser_version": Config.MEAL_UPLOAD_PARSER_VERSION,
        "uploaded_by": uploaded_by,
        "uploaded_at": uploaded_at.isoformat(),
    }
    archive_dir = Config.MEAL_UPLOAD_ARCHIVE_DIR / uploaded_at.strftime("%Y") / uploaded_at.strftime("%m") / upload_id
    result_path = store_upload_original(archive_dir, metadata, contents)
    importer, parsed = parse_upload_workbook(
        contents,
        result_path,
        metadata,
        uploaded_at.date(),
        importer_class=importer_class,
        archive_validator=archive_validator,
    )
    if importer is None or not parsed:
        return {"data": metadata}, False
    analysis = build_upload_analysis(parsed, metadata)
    metadata["analysis_status"] = "completed"
    metadata["apply_status"] = "pending"
    await apply_uploaded_meals(importer, parsed, db, result_path, metadata)
    analysis["apply_status"] = "completed"
    try:
        write_upload_result(result_path, analysis)
    except OSError:
        logger.exception("[excel_upload] 완료 결과 sidecar 기록에 실패했습니다.")
    return {"data": analysis}, False


async def sync_archived_upload(
    db: AsyncSession,
    *,
    upload_id: str | None,
    requested_by: str,
    importer_class: type[ExcelMealImporter] = ExcelMealImporter,
    archive_validator: Any = validate_xlsx_archive,
) -> dict[str, Any]:
    """Parse and apply the selected archived workbook with detailed outcome data."""
    record = upload_record(upload_id)
    if record is None:
        detail = "동기화할 업로드 파일이 없습니다." if upload_id is None else f"업로드 파일을 찾을 수 없습니다: {upload_id}"
        raise HTTPException(status_code=404, detail=detail)
    result_path, stored_result = record
    requested_at = dt.datetime.now(tz=Config.TZ).isoformat()
    base_result = {**stored_result, "sync_source": "latest" if not upload_id or not upload_id.strip() else "selected", "sync_requested_by": requested_by, "sync_requested_at": requested_at}
    try:
        contents = result_path.with_name("original.xlsx").read_bytes()
        importer, parsed = load_parsed_workbook(
            contents,
            today=dt.datetime.now(tz=Config.TZ).date(),
            importer_class=importer_class,
            archive_validator=archive_validator,
        )
    except OSError:
        return record_sync_failure(result_path, base_result, error_code="original_file_unavailable", error_message="보관된 원본 Excel 파일을 읽을 수 없습니다.", requested_at=requested_at)
    except UploadAnalysisError as exc:
        return record_sync_failure(result_path, base_result, error_code=exc.code, error_message=exc.message, requested_at=requested_at)
    try:
        await importer.insert_parsed_to_db(db, parsed)
    except Exception as exc:
        await db.rollback()
        logger.exception("[excel_sync] 메뉴 반영에 실패했습니다.")
        return record_sync_failure(result_path, base_result, error_code="excel_apply_failed", error_message=f"파일 분석은 완료했지만 DB 메뉴 반영에 실패했습니다. ({type(exc).__name__})", requested_at=requested_at)
    analysis = build_upload_analysis(parsed, base_result)
    analysis.update({"sync_status": "completed", "sync_error_code": None, "sync_error_message": None, "synced_at": dt.datetime.now(tz=Config.TZ).isoformat()})
    try:
        write_upload_result(result_path, analysis)
    except OSError:
        logger.exception("[excel_sync] 완료 결과 sidecar 기록에 실패했습니다.")
    return analysis


def sync_lock():
    """Expose the shared workbook lock to the route layer."""
    return _sync_lock
