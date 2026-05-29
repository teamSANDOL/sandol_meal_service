# 📌 산돌이 학식 서비스 API

## 📂 프로젝트 개요  
한국공학대학교 학식 및 교내외 업체들의 메뉴를 등록 및 제공하는 API 서버입니다.
- 한국공학대학교의 학식 메뉴 정보를 크롤링하여 제공합니다.
- 교내외 업체들이 서버에 메뉴를 등록합니다.
- 등록된 각 식당의 메뉴 정보를 제공합니다.

---

## 📌 프로젝트 구조  
- **Python 3.11**
- **FastAPI**
- **Docker**    

---

## 📌 문서  
- **제작된 API 문서 (Swagger, Notion 활용 등) 바로가기 링크 명시**  

### 식당 유형 구분 기준

`sandol_meal_service`의 식당 유형(`establishment_type`)은 아래 4가지 값을 사용합니다.

| 값 | 한글 설명 | 구분 기준 |
| --- | --- | --- |
| `student` | 교내 학생식당 | 학교가 운영하거나 학생식당으로 취급하는 교내 식당입니다. 현재 seed 데이터(TIP 가가식당, E동 레스토랑)도 이 유형을 사용합니다. |
| `fixed_menu_restaurant` | 고정메뉴일반식당 | 한식 뷔페가 아니며, 일반 식당 형태로 운영되는 식당입니다. 과거 `vendor` 값은 모두 이 유형으로 이관됩니다. |
| `fixed_korean_buffet` | 고정메뉴형 한식뷔페 | 한식 뷔페 형태이며, 1인분 가격이 고정적으로 관리되는 식당입니다. 과거 `external` 값은 모두 이 유형으로 이관됩니다. |
| `variable_korean_buffet` | 메뉴 변경형 한식뷔페 | 한식 뷔페 형태이며, 메뉴가 바뀌는 유형의 식당입니다. |

#### 판정 원칙

1. **학생식당 여부가 최우선이면 `student`**
   - 학교 내부 학생식당으로 취급하면 `student`를 사용합니다.
   - 현재 코드상 seed 데이터는 모두 `student`입니다.

2. **한식 뷔페인지 여부가 다음 기준입니다**
   - 한식 뷔페가 아니면 `fixed_menu_restaurant`입니다.
   - 한식 뷔페이면 `fixed_korean_buffet` 또는 `variable_korean_buffet` 중 하나를 사용합니다.

3. **뷔페가 아닌 일반 식당은 `fixed_menu_restaurant`**
   - 과거 `vendor`는 이제 더 이상 쓰지 않으며, 모두 `fixed_menu_restaurant`로 관리합니다.

4. **한식 뷔페 2종은 모두 `price`가 필요합니다**
   - `fixed_korean_buffet`
   - `variable_korean_buffet`
   - 두 유형은 등록 요청 시 `price`(1인분 가격, 원 단위)가 필수입니다.

5. **`is_campus`는 식당 유형과 별개의 필드입니다**
   - 현재 코드상 `is_campus`는 독립적인 위치 정보 필드입니다.
   - 즉, meal-service는 현재 `student`는 반드시 교내여야 한다거나, `fixed_menu_restaurant`는 반드시 교외여야 한다는 식의 강제 규칙을 두고 있지 않습니다.

#### 현재 운영/마이그레이션 기준

- `external -> fixed_korean_buffet`
- `vendor -> fixed_menu_restaurant`

따라서 현재 canonical establishment type 값은 아래 4개입니다.

```text
student
fixed_menu_restaurant
fixed_korean_buffet
variable_korean_buffet
```

---
## 📌 환경 설정  
- **모든 서비스는 Docker 기반으로 실행되므로, 로컬 환경에 별도로 의존하지 않음**  
- **환경 변수 파일 (`.env`) 필요 시, 샘플 파일 (`.env.example`) 제공**
- **Keycloak 외부 도메인은 루트 `.env`의 `SERVICE_DOMAIN`으로 관리하며, compose가 이를 `KC_HOSTNAME`으로 주입함**
  - 변수명을 `KC_HOSTNAME`으로 두지 않은 이유는 같은 도메인 값을 다른 서비스에서도 재사용할 수 있게 하기 위함
- **Docker Compose를 통해 서비스 간 네트워크 및 볼륨을 설정**
- 기본 데이터베이스는 **PostgreSQL**을 사용합니다.

### 📌 실행 방법  
#### 1. 단일 서비스 실행 (개발 및 테스트)  
```bash
docker compose up -d
```
#### 2. 서비스 중지  
```bash
docker compose down
```
#### 3. 환경 변수 변경 후 재시작  
```bash
docker compose up -d --build
```

---

## 📌 배포 가이드  
- **배포 환경: Docker 기반 컨테이너 운영**  
- **CI/CD 적용 여부 및 배포 자동화 여부 명시**  
- **배포 환경 변수 (`.env`) 관리 및 보안 고려**  
- **배포 절차**  
  1. 최신 코드 Pull  
  2. 기존 컨테이너 중지 및 제거  
  3. 새로운 이미지 빌드 및 실행  
  ```bash
  docker compose down
  docker compose pull
  docker compose up -d --build
  ```
- **서버 상태 확인 및 로그 확인**  
  ```bash
  docker ps
  docker logs -f <컨테이너_ID>
  ```

---

## 📌 문의  
- **디스코드 채널 링크 삽입**  

---
🚀 **산돌이 프로젝트와 함께 효율적인 개발 환경을 만들어갑시다!**
