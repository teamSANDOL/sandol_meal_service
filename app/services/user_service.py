"""Authentication Service Module."""

from cachetools import TTLCache

from fastapi import HTTPException
from keycloak import KeycloakGetError, KeycloakOpenID, KeycloakAdmin
from keycloak.exceptions import KeycloakError

from app.models.user import User
from app.config import Config, logger
from app.schemas.users import AdminUserSchema

UserProfile = dict[str, str | None]

#: user_id → 검증된 프로필. 목록 응답의 반복 조회를 흡수하는 짧은 LRU/TTL 캐시.
_PROFILE_CACHE_TTL_SECONDS = 300
_PROFILE_CACHE_MAX_ENTRIES = 1024
_PROFILE_CACHE: TTLCache[str, UserProfile] = TTLCache(
    maxsize=_PROFILE_CACHE_MAX_ENTRIES,
    ttl=_PROFILE_CACHE_TTL_SECONDS,
)


def _string_or_none(value: object) -> str | None:
    """문자열 값만 정규화해 반환합니다."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def get_keycloak_client() -> KeycloakOpenID:
    """동기 KeycloakOpenID 인스턴스를 생성합니다."""
    return KeycloakOpenID(
        server_url=Config.KC_SERVER_URL,
        realm_name=Config.KC_REALM,
        client_id=Config.KC_CLIENT_ID,
        client_secret_key=Config.KC_CLIENT_SECRET,
        timeout=10,
    )


def get_local_keycloak_admin_client() -> KeycloakAdmin:
    """로컬 KeycloakAdmin 인스턴스를 생성합니다."""
    return KeycloakAdmin(
        server_url=Config.KC_LOCAL_URL,
        realm_name=Config.KC_REALM,
        client_id=Config.KC_CLIENT_ID,
        client_secret_key=Config.KC_CLIENT_SECRET,
        verify=True,
        timeout=10,
    )


def get_keycloak_admin_client() -> KeycloakAdmin:
    """KeycloakAdmin 인스턴스를 생성합니다."""
    return KeycloakAdmin(
        server_url=Config.KC_SERVER_URL,
        realm_name=Config.KC_REALM,
        client_id=Config.KC_CLIENT_ID,
        client_secret_key=Config.KC_CLIENT_SECRET,
        verify=True,
        timeout=10,
    )


async def keycloak_user_exists_by_id(user_id: str) -> bool:
    """user_id(=Keycloak user_id)로 사용자 존재 여부만 확인합니다.

    - 존재: True
    - 404: False
    - 그 외: 예외
    """
    admin = get_local_keycloak_admin_client()
    try:
        await admin.a_get_user(user_id=user_id)  # sub가 Keycloak user UUID라는 전제
        return True
    except KeycloakGetError as e:
        if getattr(e, "response_code", None) == Config.HttpStatus.NOT_FOUND:
            return False
        logger.error("Keycloak 사용자 조회 중 오류 발생", exc_info=e)
        raise HTTPException(
            status_code=Config.HttpStatus.INTERNAL_SERVER_ERROR,
            detail="사용자 조회 중 오류가 발생했습니다.",
        ) from e
    except KeycloakError as e:
        logger.error("Keycloak 사용자 조회 중 오류 발생", exc_info=e)
        raise HTTPException(
            status_code=Config.HttpStatus.INTERNAL_SERVER_ERROR,
            detail="사용자 조회 중 오류가 발생했습니다.",
        ) from e


async def get_cached_user_profile(user_id: str) -> dict[str, str | None]:
    """TTL 캐시를 거쳐 Keycloak 사용자 프로필을 조회합니다.

    목록 응답처럼 같은 사용자를 반복 조회하는 경로에서 Keycloak 부하를 줄입니다.
    """
    try:
        return _PROFILE_CACHE[user_id].copy()
    except KeyError:
        profile, cacheable = await _fetch_user_profile(user_id)
        if cacheable:
            _PROFILE_CACHE[user_id] = profile.copy()
        return profile.copy()


async def get_keycloak_user_profile(user_id: str) -> dict[str, str | None]:
    """Keycloak user_id로 승인 화면 표시용 사용자 프로필을 조회합니다."""
    profile, _ = await _fetch_user_profile(user_id)
    return profile


async def _fetch_user_profile(user_id: str) -> tuple[UserProfile, bool]:
    """Keycloak 프로필을 조회하고 캐시 가능 여부를 함께 반환합니다.

    Keycloak 조회 실패와 불완전한 응답은 기존 표시용 fallback을 반환하지만,
    다음 호출에서 재시도할 수 있도록 캐시하지 않습니다. 예상하지 못한 예외는
    호출자에게 그대로 전파합니다.
    """
    admin = get_local_keycloak_admin_client()
    try:
        data = await admin.a_get_user(user_id=user_id)
    except (KeycloakGetError, KeycloakError):
        logger.warning("Keycloak 사용자 프로필 조회 실패: user_id=%s", user_id)
        return _fallback_user_profile(user_id), False

    profile = _parse_user_profile(user_id, data)
    if profile is None:
        logger.warning(
            "Keycloak 사용자 프로필 응답이 불완전합니다: user_id=%s", user_id
        )
        return _fallback_user_profile(user_id), False
    return profile, True


def _fallback_user_profile(user_id: str) -> UserProfile:
    """프로필 조회 실패 시 기존 화면 계약을 위한 fallback을 생성합니다."""
    return {
        "user_id": user_id,
        "display_name": user_id,
        "username": None,
        "email": None,
    }


def _parse_user_profile(user_id: str, data: object) -> UserProfile | None:
    """완전한 Keycloak 응답을 표시용 프로필로 정규화합니다."""
    if not isinstance(data, dict) or data.get("id") != user_id:
        return None

    attributes = data.get("attributes")
    attribute_name = None
    if isinstance(attributes, dict):
        for key in ("displayName", "name", "nickname"):
            values = attributes.get(key)
            if isinstance(values, list) and values:
                attribute_name = _string_or_none(values[0])
                if attribute_name:
                    break

    first_name = _string_or_none(data.get("firstName"))
    last_name = _string_or_none(data.get("lastName"))
    full_name = " ".join(part for part in (last_name, first_name) if part).strip()
    username = _string_or_none(data.get("username"))
    email = _string_or_none(data.get("email"))
    display_name = attribute_name or full_name or username or email or user_id

    return {
        "user_id": user_id,
        "display_name": display_name,
        "username": username,
        "email": email,
    }


async def check_admin_user(user: User) -> AdminUserSchema:
    """global_admin(realm) OR meal_admin(client) 여부 확인"""
    global_admin = False
    meal_admin = False
    keycloak_admin: KeycloakAdmin = get_keycloak_admin_client()

    try:
        # 1) realm role 확인
        realm_roles = await keycloak_admin.a_get_realm_roles_of_user(user.user_id)
        if any(
            r.get("name") == Config.REALM_GLOBAL_ADMIN_ROLE for r in (realm_roles or [])
        ):
            global_admin = True

        # 2) client role 확인 (meal_admin)
        client_uuid = await keycloak_admin.a_get_client_id(Config.KC_CLIENT_ID)
        if client_uuid:
            client_roles = await keycloak_admin.a_get_client_roles_of_user(
                user_id=user.user_id,
                client_id=client_uuid,
            )
            if any(
                r.get("name") == Config.MEAL_CLIENT_ADMIN_ROLE
                for r in (client_roles or [])
            ):
                meal_admin = True

        return AdminUserSchema(
            id=user.id,
            user_id=user.user_id,
            global_admin=global_admin,
            meal_admin=meal_admin,
            created_at=user.created_at,
        )

    except Exception as e:
        logger.exception("관리자 권한 확인 중 오류 발생: user_id=%s", user.user_id)
        raise HTTPException(
            status_code=Config.HttpStatus.INTERNAL_SERVER_ERROR,
            detail="관리자 권한 조회에 실패했습니다.",
        ) from e
