"""Tests for weekly synchronization targeting and state transitions."""

from __future__ import annotations

import asyncio
import datetime as dt
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncIterator

import pytest

from app.config import Config
from app.services import crawler_service as crawler
from app.services.excel_importer import ParsedMeal


def _at(year: int, month: int, day: int, hour: int = 9) -> dt.datetime:
    """Return a timezone-aware instant suitable for scheduler tests."""
    return dt.datetime(year, month, day, hour, tzinfo=dt.timezone.utc).astimezone(
        Config.TZ
    )


def _meal(meal_date: dt.date) -> ParsedMeal:
    """Return the smallest valid parsed meal for a workbook date."""
    return ParsedMeal(
        restaurant_id=1,
        meal_type="lunch",
        date=meal_date,
        menu=["menu"],
    )


class MutableDateTime(dt.datetime):
    """Datetime replacement whose current instant is controlled by a test."""

    current = _at(2026, 9, 9)

    @classmethod
    def now(cls, tz: dt.tzinfo | None = None) -> dt.datetime:
        """Return the configured instant in the requested timezone."""
        if tz is None:
            return cls.current.replace(tzinfo=None)
        return cls.current.astimezone(tz)


@dataclass
class DownloaderProbe:
    """Record workbook download attempts."""

    calls: int = 0
    last_modified: dt.datetime = field(default_factory=lambda: _at(2026, 9, 9))
    file_name: str = "meal.xlsx"

    async def get_file(self, path: str) -> None:
        """Record one download without touching the filesystem."""
        del path
        self.calls += 1


@dataclass
class ImporterProbe:
    """Return configured meals and optionally fail database imports."""

    parsed: list[ParsedMeal]
    parse_calls: int = 0
    insert_calls: int = 0
    failures_remaining: int = 0

    def parse(self, today: dt.date | None = None) -> list[ParsedMeal]:
        """Record parsing and return the configured workbook contents."""
        del today
        self.parse_calls += 1
        return self.parsed

    async def insert_parsed_to_db(
        self,
        session: object,
        parsed: list[ParsedMeal],
    ) -> None:
        """Record imports and raise configured failures without swallowing them."""
        del session, parsed
        self.insert_calls += 1
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("database import failed")


@dataclass
class SyncHarness:
    """Mutable probes and clock for one synchronization test."""

    downloader: DownloaderProbe
    importer: ImporterProbe

    def set_now(self, value: dt.datetime) -> None:
        """Advance the scheduler clock."""
        MutableDateTime.current = value


@pytest.fixture
def sync_harness(monkeypatch: pytest.MonkeyPatch) -> SyncHarness:
    """Install isolated synchronization state and side-effect probes."""
    downloader = DownloaderProbe()
    importer = ImporterProbe(parsed=[_meal(dt.date(2026, 9, 7))])

    @asynccontextmanager
    async def session_factory() -> AsyncIterator[object]:
        yield object()

    monkeypatch.setattr(crawler.dt, "datetime", MutableDateTime)
    monkeypatch.setattr(crawler, "_sync_lock", asyncio.Lock())
    monkeypatch.setattr(crawler, "_last_file_hash", None)
    monkeypatch.setattr(crawler, "_last_parsed_week_monday", None)
    monkeypatch.setattr(crawler, "_last_synced_week_monday", None)
    monkeypatch.setattr(crawler, "_last_checked_at", None)
    monkeypatch.setattr(crawler, "_file_hash", lambda path: "same-hash")
    monkeypatch.setattr(crawler, "archive_excel", lambda active: "archive.xlsx")
    monkeypatch.setattr(crawler, "ExcelMealImporter", lambda: importer)
    monkeypatch.setattr(crawler, "AsyncSessionLocal", session_factory)
    MutableDateTime.current = _at(2026, 9, 9)
    return SyncHarness(downloader=downloader, importer=importer)


def test_target_week_monday_for_monday_to_saturday() -> None:
    """Monday through Saturday target their current week's Monday."""
    monday = dt.date(2026, 9, 7)
    for offset in range(6):
        assert crawler.target_week_monday(monday + dt.timedelta(days=offset)) == monday


def test_target_week_monday_for_sunday() -> None:
    """Sunday starts discovery for the next Monday."""
    assert crawler.target_week_monday(dt.date(2026, 9, 13)) == dt.date(2026, 9, 14)


@pytest.mark.asyncio
async def test_stale_week_remains_in_discovery(sync_harness: SyncHarness) -> None:
    """A successfully imported stale workbook is checked again on the next tick."""
    sync_harness.importer.parsed = [_meal(dt.date(2026, 8, 31))]

    await crawler.download_and_save_excel_to_db(downloader=sync_harness.downloader)
    sync_harness.set_now(_at(2026, 9, 9, 10))
    await crawler.download_and_save_excel_to_db(downloader=sync_harness.downloader)

    assert crawler._last_parsed_week_monday == dt.date(2026, 8, 31)
    assert crawler._last_synced_week_monday is None
    assert sync_harness.downloader.calls == 2


@pytest.mark.asyncio
async def test_current_week_enters_watch_mode(sync_harness: SyncHarness) -> None:
    """A successful import for the target week records watch-mode state."""
    parsed = await crawler.download_and_save_excel_to_db(
        downloader=sync_harness.downloader
    )

    assert parsed == sync_harness.importer.parsed
    assert crawler._last_file_hash == "same-hash"
    assert crawler._last_parsed_week_monday == dt.date(2026, 9, 7)
    assert crawler._last_synced_week_monday == dt.date(2026, 9, 7)


@pytest.mark.asyncio
async def test_watch_mode_under_six_hours_does_not_download(
    sync_harness: SyncHarness,
) -> None:
    """Watch mode suppresses downloads until the six-hour interval expires."""
    await crawler.download_and_save_excel_to_db(downloader=sync_harness.downloader)
    sync_harness.set_now(_at(2026, 9, 9, 14))

    result = await crawler.download_and_save_excel_to_db(
        downloader=sync_harness.downloader
    )

    assert result == []
    assert sync_harness.downloader.calls == 1
    assert sync_harness.importer.insert_calls == 1


@pytest.mark.asyncio
async def test_force_bypasses_watch_interval_and_same_hash(
    sync_harness: SyncHarness,
) -> None:
    """A forced run downloads and imports even during watch mode with the same hash."""
    await crawler.download_and_save_excel_to_db(downloader=sync_harness.downloader)
    sync_harness.set_now(_at(2026, 9, 9, 10))

    result = await crawler.download_and_save_excel_to_db(
        force=True,
        downloader=sync_harness.downloader,
    )

    assert result == sync_harness.importer.parsed
    assert sync_harness.downloader.calls == 2
    assert sync_harness.importer.parse_calls == 2
    assert sync_harness.importer.insert_calls == 2


@pytest.mark.asyncio
async def test_saturday_preupload_same_hash_enters_watch_on_sunday(
    sync_harness: SyncHarness,
) -> None:
    """A successfully imported next-week file is recognized unchanged on Sunday."""
    sync_harness.set_now(_at(2026, 9, 12))
    sync_harness.importer.parsed = [_meal(dt.date(2026, 9, 14))]
    await crawler.download_and_save_excel_to_db(downloader=sync_harness.downloader)

    assert crawler._last_synced_week_monday is None
    assert sync_harness.importer.insert_calls == 1

    sync_harness.set_now(_at(2026, 9, 13))
    result = await crawler.download_and_save_excel_to_db(
        downloader=sync_harness.downloader
    )

    assert result == []
    assert sync_harness.downloader.calls == 2
    assert sync_harness.importer.insert_calls == 1
    assert crawler._last_synced_week_monday == dt.date(2026, 9, 14)


@pytest.mark.asyncio
async def test_sunday_tuesday_start_is_classified_as_target_week(
    sync_harness: SyncHarness,
) -> None:
    """A workbook missing Monday still maps its first Tuesday to that Monday."""
    sync_harness.set_now(_at(2026, 9, 13))
    sync_harness.importer.parsed = [
        _meal(dt.date(2026, 9, 15)),
        _meal(dt.date(2026, 9, 16)),
    ]

    await crawler.download_and_save_excel_to_db(downloader=sync_harness.downloader)

    assert crawler._last_parsed_week_monday == dt.date(2026, 9, 14)
    assert crawler._last_synced_week_monday == dt.date(2026, 9, 14)


@pytest.mark.asyncio
async def test_concurrent_forced_calls_are_serialized(
    sync_harness: SyncHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The process lock prevents download/import pipelines from overlapping."""
    entered_first = asyncio.Event()
    release_first = asyncio.Event()
    active_downloads = 0
    maximum_active_downloads = 0

    async def blocking_get_file(path: str) -> None:
        nonlocal active_downloads, maximum_active_downloads
        del path
        sync_harness.downloader.calls += 1
        active_downloads += 1
        maximum_active_downloads = max(maximum_active_downloads, active_downloads)
        if sync_harness.downloader.calls == 1:
            entered_first.set()
            await release_first.wait()
        await asyncio.sleep(0)
        active_downloads -= 1

    monkeypatch.setattr(sync_harness.downloader, "get_file", blocking_get_file)
    first = asyncio.create_task(
        crawler.download_and_save_excel_to_db(
            force=True,
            downloader=sync_harness.downloader,
        )
    )
    await entered_first.wait()
    second = asyncio.create_task(
        crawler.download_and_save_excel_to_db(
            force=True,
            downloader=sync_harness.downloader,
        )
    )
    await asyncio.sleep(0)

    assert sync_harness.downloader.calls == 1
    release_first.set()
    await asyncio.gather(first, second)

    assert sync_harness.downloader.calls == 2
    assert sync_harness.importer.insert_calls == 2
    assert maximum_active_downloads == 1


@pytest.mark.asyncio
async def test_import_failure_retries_same_hash_without_marking_synced(
    sync_harness: SyncHarness,
) -> None:
    """A failed DB import cannot make its hash eligible for the success shortcut."""
    sync_harness.importer.failures_remaining = 1

    with pytest.raises(RuntimeError, match="database import failed"):
        await crawler.download_and_save_excel_to_db(downloader=sync_harness.downloader)

    assert crawler._last_file_hash is None
    assert crawler._last_parsed_week_monday is None
    assert crawler._last_synced_week_monday is None

    result = await crawler.download_and_save_excel_to_db(
        downloader=sync_harness.downloader
    )

    assert result == sync_harness.importer.parsed
    assert sync_harness.downloader.calls == 2
    assert sync_harness.importer.insert_calls == 2
    assert crawler._last_file_hash == "same-hash"
    assert crawler._last_synced_week_monday == dt.date(2026, 9, 7)


@pytest.mark.asyncio
async def test_partial_parse_retries_same_hash_without_marking_synced(
    sync_harness: SyncHarness,
) -> None:
    """A rejected partial parse leaves its hash eligible for the next run."""
    valid_parsed = sync_harness.importer.parsed
    sync_harness.importer.parsed = []

    first_result = await crawler.download_and_save_excel_to_db(
        downloader=sync_harness.downloader
    )

    assert first_result == []
    assert crawler._last_file_hash is None
    assert crawler._last_parsed_week_monday is None
    assert crawler._last_synced_week_monday is None
    assert crawler._last_checked_at is None
    assert sync_harness.importer.insert_calls == 0

    sync_harness.importer.parsed = valid_parsed
    second_result = await crawler.download_and_save_excel_to_db(
        downloader=sync_harness.downloader
    )

    assert second_result == valid_parsed
    assert sync_harness.downloader.calls == 2
    assert sync_harness.importer.parse_calls == 2
    assert sync_harness.importer.insert_calls == 1
    assert crawler._last_file_hash == "same-hash"
    assert crawler._last_synced_week_monday == dt.date(2026, 9, 7)


@pytest.mark.asyncio
async def test_failed_saturday_preupload_cannot_shortcut_sunday(
    sync_harness: SyncHarness,
) -> None:
    """Sunday retries a same-hash pre-upload unless Saturday imported it successfully."""
    sync_harness.set_now(_at(2026, 9, 12))
    sync_harness.importer.parsed = [_meal(dt.date(2026, 9, 14))]
    sync_harness.importer.failures_remaining = 1

    with pytest.raises(RuntimeError, match="database import failed"):
        await crawler.download_and_save_excel_to_db(downloader=sync_harness.downloader)

    sync_harness.set_now(_at(2026, 9, 13))
    result = await crawler.download_and_save_excel_to_db(
        downloader=sync_harness.downloader
    )

    assert result == sync_harness.importer.parsed
    assert sync_harness.downloader.calls == 2
    assert sync_harness.importer.insert_calls == 2
    assert crawler._last_synced_week_monday == dt.date(2026, 9, 14)


@pytest.mark.asyncio
async def test_archive_failure_is_propagated_and_same_hash_is_retried(
    sync_harness: SyncHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An archive failure leaves no successful hash state and is not swallowed."""
    archive_calls = 0

    def fail_once(active: object) -> str:
        nonlocal archive_calls
        del active
        archive_calls += 1
        if archive_calls == 1:
            raise OSError("archive failed")
        return "archive.xlsx"

    monkeypatch.setattr(crawler, "archive_excel", fail_once)

    with pytest.raises(OSError, match="archive failed"):
        await crawler.download_and_save_excel_to_db(downloader=sync_harness.downloader)

    assert crawler._last_file_hash is None
    assert crawler._last_parsed_week_monday is None
    assert crawler._last_synced_week_monday is None

    result = await crawler.download_and_save_excel_to_db(
        downloader=sync_harness.downloader
    )

    assert result == sync_harness.importer.parsed
    assert archive_calls == 2
    assert sync_harness.importer.insert_calls == 1
