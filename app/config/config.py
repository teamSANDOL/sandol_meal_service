"""FastAPI 앱의 설정을 정의하는 모듈입니다.

이 모듈은 환경 변수를 로드하고, 로깅을 설정하며, FastAPI 애플리케이션의 설정 값을 관리하는 Config 클래스를 제공합니다.
또한, meal_types.json 파일에서 식사 유형을 불러오는 기능도 포함되어 있습니다.
"""

import os
import logging
import json
from dotenv import load_dotenv
from pytz import timezone

from fastapi_pagination.utils import disable_installed_extensions_check

# 환경 변수 로딩
load_dotenv()

disable_installed_extensions_check()

# 현재 파일이 위치한 디렉터리 (config 폴더의 절대 경로)
CONFIG_DIR = os.path.dirname(__file__)
CONFIG_DIR = os.path.abspath(CONFIG_DIR)

SERVICE_DIR = os.path.abspath(os.path.join(CONFIG_DIR, "../.."))

# tmp_dir make
if not os.path.exists(os.path.join(SERVICE_DIR, "tmp")):
    os.makedirs(os.path.join(SERVICE_DIR, "tmp"))

# 로깅 설정
logger = logging.getLogger("sandol_meal_service")
logger.setLevel(logging.DEBUG)  # 모든 로그 기록

# 핸들러 1: 파일에 모든 로그 저장 (디버깅용)
file_handler = logging.FileHandler(
    os.path.join(SERVICE_DIR, "app.log"), encoding="utf-8"
)
file_handler.setLevel(logging.DEBUG)  # DEBUG 이상 저장
file_formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"
)
file_handler.setFormatter(file_formatter)

# 핸들러 2: 콘솔에 INFO 이상만 출력 (간결한 버전)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)  # INFO 이상만 출력
console_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
console_handler.setFormatter(console_formatter)

# 로거에 핸들러 추가
logger.addHandler(file_handler)
logger.addHandler(console_handler)


class Config:
    """FastAPI 설정 값을 관리하는 클래스

    이 클래스는 환경 변수에서 설정 값을 로드하고, 기본 값을 제공합니다.
    또한, meal_types.json 파일에서 식사 유형을 불러오는 기능도 포함되어 있습니다.
    """

    debug = os.getenv("DEBUG", "False").lower() == "true"

    SERVICE_ID: str = str(os.getenv("SERVICE_ID", 6))

    SERVICE_DIR = SERVICE_DIR
    CONFIG_DIR = CONFIG_DIR
    TMP_DIR = os.path.join(SERVICE_DIR, "tmp")

    USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://user-service:8000")
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./meal_service.db")

    TIMEZONE = os.getenv("TIMEZONE", "Asia/Seoul")
    TZ = timezone(TIMEZONE)

    MIN_TEST_USERS = 2

    class HttpStatus:
        """HTTP 상태 코드를 정의하는 클래스"""

        OK = 200
        CREATED = 201
        NO_CONTENT = 204
        BAD_REQUEST = 400
        UNAUTHORIZED = 401
        FORBIDDEN = 403
        NOT_FOUND = 404
        CONFLICT = 409
        INTERNAL_SERVER_ERROR = 500

    @staticmethod
    def get_meal_types_file():
        """meal_types.json 파일 경로 반환

        Returns:
            str: meal_types.json 파일의 절대 경로
        """
        return os.path.join(
            CONFIG_DIR, os.getenv("MEAL_TYPES_FILE_NAME", "meal_types.json")
        )

    @staticmethod
    def load_meal_types():
        """meal_types.json에서 식사 유형을 불러옴

        Returns:
            list: meal_types.json 파일에서 불러온 식사 유형 리스트. 파일이 없거나 손상된 경우 빈 리스트 반환.
        """
        meal_types_file = Config.get_meal_types_file()
        try:
            with open(meal_types_file, "r", encoding="utf-8") as file:
                data = json.load(file)
                return data.get("meal_types", [])
        except (FileNotFoundError, json.JSONDecodeError):
            logger.warning(
                "⚠️ %s 파일이 없거나 손상됨. 빈 리스트 반환.", meal_types_file
            )
            return []
