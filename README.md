# B2B 온라인 카지노 게임 통합 플랫폼

B2B 온라인 카지노 게임 통합 플랫폼은 카지노 운영사, 게임 어그리게이터, 제휴사 등 다양한 비즈니스 파트너에게 고성능 API 서비스를 제공하는 시스템입니다.

## 주요 기능

- **파트너 관리 시스템**: 비즈니스 파트너 정보, 계약, 수수료 모델 관리
- **API 키 인증 및 권한 관리**: 보안 API 키 발급 및 세밀한 권한 관리
- **게임 통합 API**: 다양한 게임 제공자와의 원활한 통합
- **지갑 API**: 입출금, 베팅, 승리 처리 등 금융 거래 관리
- **보고서 및 정산 시스템**: 상세한 트랜잭션 내역 및 정산 보고서
- **다중 통화 지원**: 글로벌 운영을 위한 다양한 통화 처리
- **보안 기능**: IP 화이트리스팅, 암호화 등 강력한 보안 기능
- **AML(자금세탁방지) 모니터링**: 규제 준수를 위한 트랜잭션 모니터링

## 기술 스택

- **백엔드**: Python 3.11, FastAPI
- **데이터베이스**: PostgreSQL, Redis
- **메시지 큐**: Kafka
- **인프라**: Docker, Kubernetes

## 프로젝트 구조
backend/
├── alembic/                  # 데이터베이스 마이그레이션
├── api/                      # API 엔드포인트
│   ├── dependencies/         # API 종속성 (인증 등)
│   ├── errors/               # 오류 핸들러
│   ├── routers/              # 도메인별 API 라우트
│   └── api.py                # 메인 API 설정
├── core/                     # 핵심 애플리케이션 구성요소
│   ├── config.py             # 설정
│   ├── security.py           # 보안 유틸리티
│   └── events.py             # 이벤트 처리
├── db/                       # 데이터베이스
│   ├── database.py           # 데이터베이스 연결
│   └── repositories/         # 데이터베이스 리포지토리
├── models/                   # 데이터 모델
│   ├── domain/               # 도메인 모델 (SQLAlchemy)
│   └── schemas/              # API 스키마 (Pydantic)
├── services/                 # 비즈니스 로직
│   ├── partner/              # 파트너 관리
│   ├── auth/                 # 인증
│   ├── game/                 # 게임 통합
│   ├── wallet/               # 지갑 관리
│   ├── reporting/            # 보고서 및 정산
│   └── aml/                  # 자금세탁방지
├── utils/                    # 유틸리티 함수
├── domain_events/            # 도메인 이벤트 시스템
├── cache/                    # 캐싱 시스템
├── tests/                    # 테스트
├── main.py                   # 애플리케이션 진입점
└── docker-compose.yml        # Docker Compose 구성

## 설치 및 실행

### 요구 사항

- Python 3.11+
- PostgreSQL 13+
- Redis 6+
- Kafka 2.8+

### 개발 환경 설정

1. 저장소 복제

```bash
git clone https://github.com/your-username/b2b-casino-platform.git
cd b2b-casino-platform

가상 환경 생성 및 활성화

bashpython -m venv venv
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate  # Windows

의존성 설치

bashpip install -r requirements.txt

환경 변수 설정

.env 파일을 생성하여 필요한 환경 변수 설정:
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/casino_platform
REDIS_URL=redis://localhost:6379/0
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
SECRET_KEY=your-secret-key
ENVIRONMENT=development

데이터베이스 마이그레이션

bashalembic upgrade head

개발 서버 실행

bashuvicorn backend.main:app --reload
Docker 실행
Docker Compose를 사용하여 전체 스택 실행:
bashdocker-compose up -d
API 문서
개발 모드에서 API 문서는 다음 URL에서 확인할 수 있습니다:

Swagger UI: http://localhost:8000/api/docs
ReDoc: http://localhost:8000/api/redoc

테스트
테스트 실행:
bashpytest
특정 테스트 실행:
bashpytest tests/services/test_wallet_service.py
라이선스
이 프로젝트는 비공개 소프트웨어입니다. 무단 사용 및 배포를 금지합니다.