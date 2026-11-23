"""iBook 접근 차단 래치, 요청 형태, 호출부 건너뛰기 테스트. 실제 네트워크는 쓰지 않는다."""

from __future__ import annotations

import datetime as dt
from typing import Any

import httpx
import pytest

from app.services import crawler_service as crawler
from app.services import ibook_downloader as ibook
from app.services.ibook_downloader import (
    BookDownloader,
    RemoteAccessBlockedError,
    UnsupportedFileTypeError,
)

FILE_LIST_XML = (
    '<rawfiles bookcode="abc"><file name="{name}" host="h.example" size="1"/>'
    "</rawfiles>"
)


class FakeClient:
    """요청을 기록하고 고정 응답을 돌려주는 httpx.AsyncClient 대체품."""

    status_code = 200
    list_name = "meal.xlsx"
    instances: list[FakeClient] = []
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def __init__(self, **kwargs: Any) -> None:
        """생성 인자(headers 등)를 보관한다."""
        self.init_kwargs = kwargs
        type(self).instances.append(self)

    async def __aenter__(self) -> FakeClient:
        """컨텍스트에 진입한다."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """컨텍스트를 종료한다."""

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """요청을 기록하고 설정된 상태 코드로 응답한다."""
        type(self).calls.append((method, url, kwargs))
        text = (
            FILE_LIST_XML.format(name=self.list_name)
            if "rawFileList" in url
            else "var bookcode = 'abc';"
        )
        return httpx.Response(
            self.status_code, text=text, request=httpx.Request(method, url)
        )


@pytest.fixture(autouse=True)
def fake_network(monkeypatch: pytest.MonkeyPatch) -> type[FakeClient]:
    """네트워크를 가짜로 바꾸고 차단 래치와 건너뛰기 상태를 초기화한다."""
    FakeClient.status_code = 200
    FakeClient.list_name = "meal.xlsx"
    FakeClient.instances = []
    FakeClient.calls = []
    monkeypatch.setattr(ibook.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(ibook, "_blocked_kinds", set())
    monkeypatch.setattr(crawler, "_skip_until", None)
    return FakeClient


@pytest.mark.asyncio
async def test_file_list_uses_new_url_body_and_shared_client() -> None:
    """뷰어 GET과 목록 POST는 같은 클라이언트이고 본문에 key가 없다."""
    downloader = BookDownloader()
    await downloader.fetch_bookcode(client := FakeClient())
    await downloader.fetch_file_list(client)

    (get_call, post_call) = FakeClient.calls
    assert get_call[0] == "GET"
    assert post_call[0] == "POST"
    assert post_call[1] == "https://ibook.tukorea.ac.kr/Viewer/rawFileList"
    assert post_call[2]["data"] == {"bookcode": "abc", "base64": "N"}
    assert len(FakeClient.instances) == 1


@pytest.mark.asyncio
async def test_fetch_file_list_without_client_shares_one_client() -> None:
    """클라이언트를 안 주면 내부에서 하나만 만들어 GET과 POST에 함께 쓴다."""
    await BookDownloader().fetch_file_list()
    assert [c[0] for c in FakeClient.calls] == ["GET", "POST"]
    assert len(FakeClient.instances) == 1
    headers = FakeClient.instances[0].init_kwargs["headers"]
    assert headers["X-Requested-With"] == "XMLHttpRequest"
    assert headers["User-Agent"] == "Mozilla/5.0 (compatible; sandol-meal-service)"
    assert "key" not in FakeClient.calls[1][2]["data"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403, 429])
async def test_blocked_status_latches_endpoint_kind(status_code: int) -> None:
    """차단 응답 후 같은 종류의 두 번째 호출은 요청 0회로 예외를 올린다."""
    FakeClient.status_code = status_code
    downloader = BookDownloader()
    with pytest.raises(RemoteAccessBlockedError):
        await downloader.fetch_bookcode()
    assert len(FakeClient.calls) == 1
    with pytest.raises(RemoteAccessBlockedError):
        await downloader.fetch_bookcode()
    assert len(FakeClient.calls) == 1


@pytest.mark.asyncio
async def test_non_excel_first_file_is_not_downloaded() -> None:
    """첫 파일이 PDF면 다운로드(download 종류) 요청 없이 예외를 올린다."""
    FakeClient.list_name = "meal.pdf"
    with pytest.raises(UnsupportedFileTypeError):
        await BookDownloader().get_file("unused.xlsx")
    assert [c[0] for c in FakeClient.calls] == ["GET", "POST"]


class _RaisingDownloader:
    """지정한 예외를 올리고 호출 횟수를 세는 다운로더."""

    def __init__(self, error: Exception) -> None:
        """올릴 예외를 설정한다."""
        self.error = error
        self.calls = 0

    async def get_file(self, path: str) -> None:
        """호출을 기록하고 예외를 올린다."""
        del path
        self.calls += 1
        raise self.error


@pytest.mark.asyncio
async def test_sync_skips_quietly_on_blocked_error() -> None:
    """차단 예외가 나면 호출부는 예외 없이 빈 목록을 돌려준다."""
    probe = _RaisingDownloader(RemoteAccessBlockedError(403, "blocked"))
    assert (
        await crawler.download_and_save_excel_to_db(force=True, downloader=probe) == []
    )


@pytest.mark.asyncio
async def test_unsupported_file_skips_six_hours_unless_forced() -> None:
    """엑셀이 아니면 6시간 동안 재조회하지 않고, force면 무시한다."""
    probe = _RaisingDownloader(UnsupportedFileTypeError(None, "pdf"))
    assert await crawler.download_and_save_excel_to_db(downloader=probe) == []
    assert await crawler.download_and_save_excel_to_db(downloader=probe) == []
    assert probe.calls == 1
    assert crawler._skip_until is not None
    assert crawler._skip_until > dt.datetime.now(tz=crawler.Config.TZ)
    await crawler.download_and_save_excel_to_db(force=True, downloader=probe)
    assert probe.calls == 2
