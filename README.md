# 📌 산돌이 Backend Repository Template  

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

---
## 📌 환경 설정  
- **모든 서비스는 Docker 기반으로 실행되므로, 로컬 환경에 별도로 의존하지 않음**  
- **환경 변수 파일 (`.env`) 필요 시, 샘플 파일 (`.env.example`) 제공**  
- **Docker Compose를 통해 서비스 간 네트워크 및 볼륨을 설정**  

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
