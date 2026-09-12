"""Scheduled download and synchronization of the weekly meal workbook."""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import os
import shutil

from app.config import Config, logger
from app.database import AsyncSessionLocal
from app.services.excel_importer import EXCEL_PATH, ExcelMealImporter, ParsedMeal
from app.services.ibook_downloader import BookDownloader

ARCHIVE_DIR = os.path.join(Config.TMP_DIR, "archive")
_last_file_hash: str | None = None
_last_parsed_week_monday: dt.date | None = None
_last_synced_week_monday: dt.date | None = None
_last_checked_at: dt.datetime | None = None
_sync_lock = asyncio.Lock()
_WATCH_INTERVAL = dt.timedelta(hours=6)
_SUNDAY = 7


def target_week_monday(today: dt.date) -> dt.date:
    """Return the Monday whose workbook should be discovered."""
    if today.isoweekday() == _SUNDAY:
        return today + dt.timedelta(days=1)
    return today - dt.timedelta(days=today.isoweekday() - 1)


def archive_excel(downloader: BookDownloader) -> str | None:
    """Archive a downloaded workbook once under its remote modification time."""
    if downloader.last_modified is None or downloader.file_name is None:
        return None
    stamp = downloader.last_modified.astimezone(Config.TZ).strftime("%Y%m%d_%H%M%S")
    destination = os.path.join(ARCHIVE_DIR, f"{stamp}_{downloader.file_name}")
    if os.path.exists(destination):
        return None
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    shutil.copyfile(EXCEL_PATH, destination)
    logger.info("[archive] 저장: %s", destination)
    return destination


def _file_hash(path: str) -> str:
    """Return a stable SHA-256 hash for a downloaded workbook."""
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parsed_week_monday(parsed: list[ParsedMeal]) -> dt.date | None:
    """Return the Monday of the parsed workbook's week."""
    if not parsed:
        return None
    first_date = min(meal.date for meal in parsed)
    return first_date - dt.timedelta(days=first_date.weekday())


async def download_and_save_excel_to_db(
    force: bool = False,
    downloader: BookDownloader | None = None,
) -> list[ParsedMeal]:  # noqa: PLW0603
    """Download, parse, and synchronize the workbook under one process lock."""
    global _last_file_hash, _last_parsed_week_monday  # noqa: PLW0603
    global _last_synced_week_monday, _last_checked_at  # noqa: PLW0603

    async with _sync_lock:
        now = dt.datetime.now(tz=Config.TZ)
        target = target_week_monday(now.date())
        watching = _last_synced_week_monday == target
        if (
            not force
            and watching
            and _last_checked_at is not None
            and now - _last_checked_at < _WATCH_INTERVAL
        ):
            return []

        active_downloader = downloader or BookDownloader()
        await active_downloader.get_file(EXCEL_PATH)
        current_hash = _file_hash(EXCEL_PATH)

        if not force and current_hash == _last_file_hash:
            _last_checked_at = now
            _last_synced_week_monday = (
                target if _last_parsed_week_monday == target else None
            )
            return []

        archive_excel(active_downloader)
        importer = ExcelMealImporter()
        parsed = importer.parse(today=now.date())
        if not parsed:
            logger.error("[meal_excel_sync] 파싱 결과가 없어 DB 반영을 건너뜁니다.")
            return []

        parsed_week_monday = _parsed_week_monday(parsed)
        async with AsyncSessionLocal() as session:
            await importer.insert_parsed_to_db(session, parsed)

        _last_file_hash = current_hash
        _last_parsed_week_monday = parsed_week_monday
        _last_checked_at = now
        if parsed_week_monday == target:
            _last_synced_week_monday = target
        else:
            _last_synced_week_monday = None
            logger.warning(
                "[meal_excel_sync] 최신 주간 파일이 아닙니다: parsed=%s target=%s",
                parsed_week_monday,
                target,
            )
        return parsed
