import httpx
from xml.etree import ElementTree
from typing import Optional

from app.config import logger


class FetchError(Exception):
    def __init__(self, status_code=None, message="파일 처리 중 오류가 발생했습니다."):
        self.status_code = status_code
        self.message = (
            f"{message} Status code: {status_code}" if status_code else message
        )
        super().__init__(self.message)


class BookDownloader:
    """한국공학대학교 iBook에서 학식 엑셀 파일을 비동기로 다운로드하는 클래스입니다."""

    def __init__(
        self,
        url: str = "https://ibook.tukorea.ac.kr/Viewer/menu02",
        file_list_url: str = "https://ibook.tukorea.ac.kr/web/RawFileList",
    ):
        self.url = url
        self.file_list_url = file_list_url
        self.bookcode = None
        self.file_name = None
        self.headers = {
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://ibook.tukorea.ac.kr",
            "Referer": url,
            "X-Requested-With": "XMLHttpRequest",
        }

    async def fetch_bookcode(self):
        async with httpx.AsyncClient() as client:
            response = await client.get(self.url, timeout=10)
            if response.status_code != 200:
                raise FetchError(response.status_code, "bookcode 요청 실패")

            for line in response.text.splitlines():
                if "var bookcode =" in line:
                    self.bookcode = line.split("=")[1].strip().strip(";").strip("'")
                    logger.info(f"[BookDownloader] bookcode: {self.bookcode}")
                    return self.bookcode

        raise FetchError(None, "bookcode를 찾을 수 없습니다.")

    async def fetch_file_list(self) -> str:
        if self.bookcode is None:
            await self.fetch_bookcode()

        data = {"key": "kpu", "bookcode": self.bookcode, "base64": "N"}
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.file_list_url,
                headers=self.headers,
                data=data,
                timeout=10,
            )

            if response.status_code != 200:
                raise FetchError(response.status_code, "파일 목록 요청 실패")

            return response.text

    def get_file_url(self, file_list_xml: str) -> str:
        root = ElementTree.fromstring(file_list_xml)
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

    async def download_file(self, file_url: str, save_as: str):
        async with httpx.AsyncClient() as client:
            response = await client.get(file_url, timeout=10)
            if response.status_code != 200:
                raise FetchError(response.status_code, "파일 다운로드 실패")
            with open(save_as, "wb") as f:
                f.write(response.content)
        logger.info(f"[BookDownloader] 파일 저장 완료 → {save_as}")

    async def get_file(self, save_as: Optional[str] = "/tmp/data.xlsx"):
        await self.fetch_bookcode()
        file_list_xml = await self.fetch_file_list()
        file_url = self.get_file_url(file_list_xml)
        await self.download_file(file_url, save_as)
