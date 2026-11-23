"""한국공학대학교 iBook 식단 파일 다운로드 기능을 제공합니다."""

from datetime import datetime
from email.utils import parsedate_to_datetime
from http import HTTPStatus
from xml.etree import ElementTree
from typing import Any, Optional

import httpx

from app.config import Config, logger


class FetchError(Exception):
    """iBook 파일 요청 또는 처리 중 발생한 오류입니다."""

    def __init__(
        self,
        status_code: int | None = None,
        message: str = "파일 처리 중 오류가 발생했습니다.",
    ) -> None:
        """오류 상태 코드와 사용자에게 표시할 메시지를 설정합니다."""
        self.status_code = status_code
        self.message = (
            f"{message} Status code: {status_code}" if status_code else message
        )
        super().__init__(self.message)


class RemoteAccessBlockedError(FetchError):
    """학교 서버가 접근을 차단했거나 이 서비스가 요청을 비활성화한 경우의 오류입니다."""


# 위장하지 않고 서비스를 밝히는 User-Agent
_USER_AGENT_HEADER = {"User-Agent": "Mozilla/5.0 (compatible; sandol-meal-service)"}
_EXCEL_SUFFIXES = (".xlsx", ".xls")

# 접근 차단(401/403/429) 응답을 받은 엔드포인트 종류. 프로세스 재시작 전까지 유지됩니다.
_BLOCKED_STATUS_CODES = frozenset(
    {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN, HTTPStatus.TOO_MANY_REQUESTS}
)
_blocked_kinds: set[str] = set()


async def _send(
    kind: str,
    client: httpx.AsyncClient | None,
    method: str,
    url: str,
    **kwargs: Any,
) -> httpx.Response:
    """학교로 요청을 보내고, 차단 응답이면 종류별로 기록해 재요청을 막습니다.

    Args:
        kind: 엔드포인트 종류(viewer, raw_file_list, book_xml, download).
        client: 쿠키를 공유할 클라이언트. None이면 일회용 클라이언트를 만듭니다.
        method: HTTP 메서드.
        url: 요청 URL.
        **kwargs: httpx 요청 인자.

    Returns:
        응답 객체.

    Raises:
        RemoteAccessBlockedError: 이미 차단된 종류이거나 이번 응답이 401/403/429인 경우.
    """
    if kind in _blocked_kinds:
        raise RemoteAccessBlockedError(None, f"학교 서버 접근 차단됨({kind})")
    if client is None:
        async with httpx.AsyncClient(headers=_USER_AGENT_HEADER) as one_shot:
            response = await one_shot.request(method, url, **kwargs)
    else:
        response = await client.request(method, url, **kwargs)
    if response.status_code in _BLOCKED_STATUS_CODES:
        _blocked_kinds.add(kind)
        logger.error(
            f"[BookDownloader] 학교 서버가 접근을 차단했습니다: {kind} "
            f"(status {response.status_code}). 재시작 전까지 요청하지 않습니다."
        )
        raise RemoteAccessBlockedError(
            response.status_code, f"학교 서버 접근 차단됨({kind})"
        )
    return response


class UnsupportedFileTypeError(FetchError):
    """파일 목록의 첫 파일이 엑셀(.xlsx/.xls)이 아닐 때의 오류입니다."""


class BookDownloader:
    """한국공학대학교 iBook에서 학식 엑셀 파일을 비동기로 다운로드하는 클래스입니다."""

    def __init__(
        self,
        url: str = "https://ibook.tukorea.ac.kr/Viewer/menu02",
        file_list_url: str = "https://ibook.tukorea.ac.kr/Viewer/rawFileList",
    ) -> None:
        """다운로드 대상 iBook 엔드포인트를 설정합니다."""
        self.url = url
        self.file_list_url = file_list_url
        self.bookcode: str | None = None
        self.file_name: str | None = None
        self.last_modified: Optional[datetime] = None
        self.headers = {
            **_USER_AGENT_HEADER,
            "Accept": "*/*",
            "Origin": "https://ibook.tukorea.ac.kr",
            "Referer": url,
            "X-Requested-With": "XMLHttpRequest",
        }

    async def fetch_bookcode(self, client: httpx.AsyncClient | None = None) -> str:
        """iBook 페이지에서 현재 bookcode를 조회합니다."""
        response = await _send("viewer", client, "GET", self.url, timeout=10)
        if response.status_code != HTTPStatus.OK:
            raise FetchError(response.status_code, "bookcode 요청 실패")

        for line in response.text.splitlines():
            if "var bookcode =" in line:
                self.bookcode = line.split("=")[1].strip().strip(";").strip("'")
                logger.info(f"[BookDownloader] bookcode: {self.bookcode}")
                return self.bookcode

        raise FetchError(None, "bookcode를 찾을 수 없습니다.")

    async def fetch_file_list(self, client: httpx.AsyncClient | None = None) -> str:
        """현재 bookcode에 연결된 원본 파일 목록 XML을 조회합니다.

        뷰어 GET과 목록 POST는 쿠키 유지를 위해 같은 클라이언트로 보냅니다.
        """
        if client is None:
            async with httpx.AsyncClient(headers=self.headers) as shared:
                return await self.fetch_file_list(shared)
        if self.bookcode is None:
            await self.fetch_bookcode(client)

        data = {"bookcode": self.bookcode, "base64": "N"}
        response = await _send(
            "raw_file_list",
            client,
            "POST",
            self.file_list_url,
            data=data,
            timeout=10,
        )
        if response.status_code != HTTPStatus.OK:
            raise FetchError(response.status_code, "파일 목록 요청 실패")

        return response.text

    def get_file_url(self, file_list_xml: str) -> str:
        """파일 목록 XML에서 원본 엑셀 파일 URL을 추출합니다."""
        root = ElementTree.fromstring(file_list_xml)  # noqa: S314 - trusted university endpoint
        for file_elem in root.findall("file"):
            file_name = file_elem.attrib["name"]
            self.file_name = file_name
            file_url = file_elem.attrib.get("file_url")
            if file_url:
                return file_url
            host = file_elem.attrib["host"]
            bookcode = root.attrib["bookcode"]
            return f"https://{host}/contents/{bookcode[0]}/{bookcode[:3]}/{bookcode}/raw/{file_name}"
        raise FetchError(None, "파일 URL을 찾을 수 없습니다.")

    @staticmethod
    def _parse_last_modified(response: httpx.Response) -> Optional[datetime]:
        value = response.headers.get("last-modified")
        return parsedate_to_datetime(value) if value else None

    async def fetch_remote_key(self) -> tuple[str, Optional[datetime]]:
        """본문 다운로드 없이 (파일 URL, Last-Modified)만 조회. 변경 감지용."""
        file_url = self.get_file_url(await self.fetch_file_list())
        response = await _send("download", None, "HEAD", file_url, timeout=10)
        if response.status_code != HTTPStatus.OK:
            raise FetchError(response.status_code, "파일 HEAD 요청 실패")
        return file_url, self._parse_last_modified(response)

    async def download_file(self, file_url: str, save_as: str) -> None:
        """원격 파일을 지정한 경로에 저장합니다."""
        response = await _send("download", None, "GET", file_url, timeout=10)
        if response.status_code != HTTPStatus.OK:
            raise FetchError(response.status_code, "파일 다운로드 실패")
        self.last_modified = self._parse_last_modified(response)
        with open(save_as, "wb") as f:
            f.write(response.content)
        logger.info(f"[BookDownloader] 파일 저장 완료 → {save_as}")

    async def get_file(self, save_as: Optional[str] = None) -> None:
        """현재 iBook 식단 파일을 다운로드합니다."""
        target_path = save_as or f"{Config.TMP_DIR}/data.xlsx"
        async with httpx.AsyncClient(headers=self.headers) as client:
            await self.fetch_bookcode(client)
            file_list_xml = await self.fetch_file_list(client)
        file_url = self.get_file_url(file_list_xml)
        if not (self.file_name or "").lower().endswith(_EXCEL_SUFFIXES):
            raise UnsupportedFileTypeError(
                None, f"엑셀이 아닌 파일이라 다운로드하지 않습니다: {self.file_name}"
            )
        await self.download_file(file_url, target_path)
