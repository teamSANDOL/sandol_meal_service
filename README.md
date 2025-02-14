# 📌 산돌이 Backend Repository Template  

## 📂 프로젝트 개요  
이 Repository는 **산돌이 프로젝트의 백엔드 서비스**를 위한 표준 템플릿입니다.  
모든 백엔드 서비스는 **Docker 컨테이너로 실행**되며, 이후 **Docker Compose를 활용하여 통합 운영**됩니다.  
일관된 개발 및 배포 환경을 유지하기 위해 이 템플릿을 사용합니다.  

---

## 📌 프로젝트 구조  
- **개발 프레임워크 및 주요 기술 스택 명시**  
- **프로젝트 실행 및 배포 방법 제공**  
- **API 문서 및 관련 개발 문서 링크 포함**  

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
