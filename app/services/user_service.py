"""Authentication Service Module."""

from fastapi import HTTPException
from keycloak import KeycloakGetError, KeycloakOpenID, KeycloakAdmin
from keycloak.exceptions import KeycloakError

from app.config import Config, logger
from app.schemas.users import AdminUserSchema
from app.models.user import User


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


async def get_keycloak_user_profile(user_id: str) -> dict[str, str | None]:
    """Keycloak user_id로 승인 화면 표시용 사용자 프로필을 조회합니다."""
    admin = get_local_keycloak_admin_client()
    try:
        data = await admin.a_get_user(user_id=user_id)
    except (KeycloakGetError, KeycloakError):
        logger.warning("Keycloak 사용자 프로필 조회 실패: user_id=%s", user_id)
        return {
            "user_id": user_id,
            "display_name": user_id,
            "username": None,
            "email": None,
        }

    attributes = data.get("attributes") if isinstance(data, dict) else None
    attribute_name = None
    if isinstance(attributes, dict):
        for key in ("displayName", "name", "nickname"):
            values = attributes.get(key)
            if isinstance(values, list) and values:
                attribute_name = _string_or_none(values[0])
                if attribute_name:
                    break

    first_name = _string_or_none(data.get("firstName")) if isinstance(data, dict) else None
    last_name = _string_or_none(data.get("lastName")) if isinstance(data, dict) else None
    full_name = " ".join(part for part in (last_name, first_name) if part).strip()
    username = _string_or_none(data.get("username")) if isinstance(data, dict) else None
    email = _string_or_none(data.get("email")) if isinstance(data, dict) else None
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
        if any(r.get("name") == Config.REALM_GLOBAL_ADMIN_ROLE for r in (realm_roles or [])):
            global_admin = True

        # 2) client role 확인 (meal_admin)
        client_uuid = await keycloak_admin.a_get_client_id(Config.KC_CLIENT_ID)
        if client_uuid:
            client_roles = await keycloak_admin.a_get_client_roles_of_user(
                user_id=user.user_id,
                client_id=client_uuid,
            )
            if any(r.get("name") == Config.MEAL_CLIENT_ADMIN_ROLE for r in (client_roles or [])):
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
