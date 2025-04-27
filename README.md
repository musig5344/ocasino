# 온라인 카지노 플랫폼 기술 문서 (상세 보완)

## 1. 개요 (Overview)

본 문서는 B2B 온라인 카지노 게임 통합 플랫폼의 기술적인 측면을 설명합니다. 이 플랫폼은 카지노 운영사, 게임 어그리게이터, 제휴사 등 다양한 비즈니스 파트너에게 안정적이고 확장 가능한 API 서비스를 제공하는 것을 목표로 합니다. 플랫폼의 핵심 기능은 모듈화된 서비스(`backend/services/` 디렉토리 내 위치)들을 통해 제공됩니다.

**주요 기능:**

*   **비즈니스 파트너 관리:** 파트너 등록, 정보 수정, API 키 발급 및 관리 (`Partner Service` 담당).
*   **게임 콘텐츠 통합 및 관리:** 외부 게임 제공사 API(예: OCasino) 연동 및 게임 관련 데이터 관리 (`Game Integration Service` 담당).
*   **통합 지갑 시스템:** 플레이어 잔액 관리, 입/출금 처리, 베팅 및 승리 시 잔액 조정 (`Wallet Service` 담당). `backend/models/domain/wallet.py`의 `Transaction` 모델을 통해 거래 기록 관리.
*   **자금세탁방지(AML) 트랜잭션 분석:** `Wallet Service` 등에서 발생하는 트랜잭션을 실시간 또는 비동기적으로 분석하여 위험 평가 수행 (`AML Service` - `backend/services/aml/aml_service.py` 담당).
*   **보고서 생성 및 정산 처리:** 다양한 기준에 따른 데이터 집계 및 보고서 생성 (`Reporting & Settlement Service` 담당).
*   **API 키 기반 인증 및 권한 관리:** 각 API 요청의 유효성 검증 및 파트너별 접근 권한 제어 (`Auth Service` 및 FastAPI 의존성 주입 활용).

**대상 사용자:**

*   **카지노 운영사:** 자체 플랫폼에 다양한 게임과 지갑 기능을 통합하려는 사업자
*   **게임 어그리게이터:** 여러 게임 제공사의 콘텐츠를 단일 API로 제공하려는 사업자
*   **제휴사:** 플랫폼의 게임 및 서비스를 홍보하고 수익을 공유하는 파트너

## 2. 기술 스택 (Technology Stack)

플랫폼은 다음과 같은 기술 스택을 기반으로 구축되었습니다.

*   **백엔드 언어 및 프레임워크:** Python 3.11, FastAPI
    *   **비동기 처리:** `async`/`await` 키워드를 적극 활용하여 I/O 바운드 작업(DB 조회, 외부 API 호출 등) 처리 성능 극대화.
    *   **데이터 유효성:** Pydantic (`backend/schemas/` 디렉토리 내 모델)을 사용하여 API 요청/응답 데이터 구조 정의 및 자동 유효성 검사 수행.
    *   **의존성 주입:** FastAPI의 의존성 주입 시스템을 활용하여 DB 세션 관리(`backend/api/dependencies/db.py`), 인증(`backend/api/dependencies/auth.py`), 설정값 주입 등을 효율적으로 처리.
*   **데이터베이스:**
    *   **PostgreSQL (SQLAlchemy 사용):** 주요 비즈니스 데이터(파트너, 지갑, 거래, 게임, AML 알림 등) 저장. SQLAlchemy ORM (`backend/models/`)을 통해 객체-관계 매핑. 비동기 작업은 `SQLAlchemy[asyncio]` 지원 활용.
    *   **Redis:**
        *   **캐싱:** 자주 조회되지만 변경 빈도가 낮은 데이터(예: 게임 목록, 파트너 설정) 캐싱하여 DB 부하 감소.
        *   **세션 관리:** 사용자/파트너 세션 정보 저장 (필요시).
        *   **임시 데이터:** 속도 제한(Rate Limiting) 카운터, 분산 락(Distributed Lock) 등 임시 데이터 저장.
*   **메시지 큐:** Kafka
    *   **주요 토픽 (예시):**
        *   `wallet.transaction.created`: 신규 거래 발생 시 `Wallet Service`가 발행. `AML Service`, `Reporting Service` 등이 구독.
        *   `aml.alert.created`: `AML Service`가 신규 알림 생성 시 발행. 알림 시스템, 케이스 관리 시스템 연동 등에 활용 가능.
        *   `partner.profile.updated`: `Partner Service`가 파트너 정보 변경 시 발행. 관련된 다른 서비스에서 구독하여 정보 동기화.
    *   **메시지 형식:** 각 토픽의 메시지는 JSON 형식이며, 관련된 이벤트 데이터 포함 (예: `wallet.transaction.created` 메시지는 생성된 Transaction의 ID, 유형, 금액, 플레이어 ID 등 포함). 이벤트 스키마는 `backend/domain_events/events.py` 등에서 정의될 수 있음.
*   **인프라:**
    *   **Docker:** 각 마이크로서비스(FastAPI 앱), 데이터베이스, Kafka, Redis 등을 개별 컨테이너로 패키징. `Dockerfile`을 통해 빌드 정의.
    *   **Kubernetes:** 컨테이너화된 애플리케이션 배포, 스케일링, 관리 자동화. `Deployment`, `Service`, `Ingress` 등의 리소스를 활용하여 서비스 구성. Helm 차트 또는 Kustomize를 사용하여 배포 관리 가능성 있음.

## 3. 아키텍처 (Architecture)

### 3.1. 주요 컴포넌트

*   **API 게이트웨이:** 외부 요청 처리, 로깅, 기본 보안 점검 후 내부 서비스로 라우팅.
*   **인증/인가 서비스 (Auth Service):**
    *   `X-API-Key` 헤더 검증 (`api/dependencies/auth.py` 내 `get_api_key` 와 같은 의존성 함수).
    *   API 키와 연결된 파트너 정보 조회 (`api_keys` 테이블 등).
    *   요청된 엔드포인트에 대한 파트너의 접근 권한 확인.
*   **파트너 관리 서비스 (Partner Service):**
    *   `partners` 테이블 관리 (CRUD).
    *   파트너별 설정(수수료율, 허용 IP 등) 관리.
    *   API 키 생성, 비활성화 로직 수행 및 `api_keys` 테이블 관리.
*   **지갑 서비스 (Wallet Service):**
    *   `wallets`, `transactions` 테이블 관리.
    *   입/출금, 베팅/승리 로직 수행 (잔액 검증, 업데이트).
    *   거래 금액 암호화/복호화 처리 (`backend/utils/encryption.py`의 함수 사용 가능성 높음. `Transaction` 모델의 `amount` 속성 접근 시 처리).
    *   성공적인 트랜잭션 발생 시 Kafka로 이벤트 발행.
*   **게임 통합 서비스 (Game Integration Service):**
    *   외부 게임 API Wrapper 역할.
    *   게임 목록(`games`, `game_providers` 테이블) 관리.
    *   게임 세션 생성 및 관리.
    *   베팅/결과 라운드 API 호출 시 `Wallet Service`와 연동하여 잔액 처리.
*   **AML 서비스 (AML Service - `aml_service.py`):**
    *   Kafka로부터 `wallet.transaction.created` 이벤트 구독.
    *   `analyze_transaction` 메서드를 통해 분석 시작.
    *   위험 요소 분석:
        *   고액 거래 (`_check_large_transaction`): 설정된 통화별 임계값(`aml_service.thresholds`) 비교.
        *   행동 패턴 편차 (`_check_behavior_pattern_deviation`): 과거 거래 내역(`wallet_repo.get_player_transactions` 조회) 기반 분석.
            *   시간 편차 (`_check_time_pattern_deviation`): 평소 거래 시간대/요일 비교.
            *   금액 편차 (`_check_amount_pattern_deviation`): 과거 평균/표준편차 대비 Z-score 계산 (`aml_service.pattern_thresholds['amount_z_score']` 임계값 사용).
            *   빈도 편차 (`_check_frequency_pattern_deviation`): 단기 거래 빈도와 장기 평균 비교 (`aml_service.pattern_thresholds['frequency_ratio']`, `['frequency_min_count']` 임계값 사용).
    *   위험 점수 계산 및 `AMLRiskProfile` 업데이트.
    *   필요시 `AMLAlert` 생성 및 저장. Kafka로 `aml.alert.created` 이벤트 발행 가능.
*   **보고서/정산 서비스 (Reporting & Settlement Service):**
    *   Kafka 이벤트 또는 스케줄링된 작업을 통해 데이터 집계.
    *   파트너별 거래량, 게임 수익, 수수료 계산.
    *   정산 보고서 생성 및 관리.

### 3.2. 데이터 흐름 예시 (플레이어 베팅 - 상세)

1.  **클라이언트 (카지노 운영사 시스템):** `POST /wallet/{player_id}/bet` 요청 (헤더: `X-API-Key: PARTNER_API_KEY`, 본문: `{ "amount": 10.0, "currency": "USD", "game_id": "game123", "round_id": "roundxyz" }`)
2.  **API 게이트웨이:** 요청 수신, `/api/wallet` 경로 확인 후 `Wallet Service` 또는 관련 라우터(`api/routers/wallet.py`)로 전달.
3.  **FastAPI 의존성 (`get_api_key` 등):** `X-API-Key` 검증, 유효한 파트너 및 권한 확인. 실패 시 401/403 응답.
4.  **Wallet Service (`place_bet` 함수 등):**
    *   요청 본문 유효성 검사 (Pydantic 모델 활용).
    *   `wallet_repo.get_wallet_for_update(player_id)` 호출하여 플레이어 지갑 정보 조회 및 락(lock).
    *   플레이어 잔액이 베팅 금액(`amount`)보다 충분한지 확인. 부족 시 400 에러 응답.
    *   **Game Integration Service** 호출하여 외부 게임 제공사 API로 실제 베팅 처리 요청 (성공/실패 확인). 게임 제공사 API 호출 실패 시 롤백 및 에러 응답.
    *   잔액 차감: `wallet.balance -= amount`.
    *   `Transaction` 객체 생성 (type=BET, status=COMPLETED, 암호화된 금액 등).
    *   `db.add(transaction)`, `db.add(wallet)`, `db.commit()`으로 DB 변경사항 저장.
    *   Kafka Producer를 사용하여 `wallet.transaction.created` 토픽으로 이벤트 메시지 발행 (JSON 형식: `{ "transaction_id": "...", "player_id": "...", "type": "BET", ... }`).
5.  **AML Service (백그라운드):** Kafka Consumer가 `wallet.transaction.created` 메시지 수신.
    *   `aml_service.analyze_transaction(transaction_id)` 비동기 호출.
    *   내부적으로 `_get_historical_transactions`, `_check_..._deviation` 등 호출하여 분석 수행.
    *   분석 결과에 따라 `AMLAlert` 생성 및 DB 저장. 필요시 `aml.alert.created` 이벤트 발행.
6.  **Wallet Service:** 클라이언트에 성공 응답 반환 (예: `{ "transaction_id": "...", "new_balance": ... }`).

### 3.3. Kafka 활용 (상세)

*   **이벤트 기반 통신:** 서비스 간 직접적인 동기 호출을 최소화하고 이벤트 발행/구독 모델을 사용하여 느슨한 결합 유지.
*   **주요 토픽 및 메시지 (예시):**
    *   **`wallet.transaction.created`**:
        ```json
        {
          "event_id": "uuid",
          "event_type": "transaction.created",
          "timestamp": "isoformat_datetime",
          "data": {
            "transaction_id": "uuid",
            "player_id": "uuid",
            "partner_id": "uuid",
            "type": "DEPOSIT | WITHDRAWAL | BET | WIN",
            "amount": float, // 실제 구현 시에는 ID만 전달하고 상세 정보는 구독자가 조회할 수도 있음
            "currency": "USD",
            "status": "COMPLETED",
            "created_at": "isoformat_datetime"
          }
        }
        ```
    *   **`aml.alert.created`**:
        ```json
        {
          "event_id": "uuid",
          "event_type": "alert.created",
          "timestamp": "isoformat_datetime",
          "data": {
            "alert_id": int,
            "player_id": "uuid",
            "transaction_id": "uuid",
            "alert_type": "THRESHOLD | PATTERN | BLACKLIST | ...",
            "alert_severity": "LOW | MEDIUM | HIGH | CRITICAL",
            "risk_score": float
          }
        }
        ```
*   **컨슈머 그룹:** 동일한 이벤트를 여러 서비스가 독립적으로 처리해야 하는 경우(예: AML 분석과 보고서 집계가 동시에 필요), 각 서비스는 별도의 컨슈머 그룹을 사용하여 메시지를 구독.
*   **메시지 처리 보장:** Kafka의 내구성을 활용하고, 컨슈머 측에서 오프셋 커밋을 신중하게 관리하여 메시지 유실 방지. 처리 실패 시 재시도 로직 또는 데드 레터 큐(Dead Letter Queue) 활용 고려.

## 4. API 명세 (API Specification) - 상세

### 4.1. 인증 (Authentication)

*   **방식:** API 키 인증.
*   **키 전달:** HTTP `X-API-Key` 요청 헤더 사용.
    ```
    X-API-Key: YOUR_PARTNER_API_KEY_HERE
    ```
*   **검증 로직:**
    1.  FastAPI 의존성 함수 (예: `api/dependencies/auth.py`의 `get_valid_api_key`)가 요청 헤더에서 `X-API-Key` 값을 읽음.
    2.  데이터베이스 (`api_keys` 테이블)에서 해당 키 조회.
    3.  키 존재 여부, 활성 상태, 연결된 파트너 정보 확인.
    4.  (선택사항) 요청 IP 주소가 해당 파트너의 화이트리스트에 등록된 IP인지 확인 (`ip_whitelist` 테이블 조회, `backend/middlewares/ip_whitelist.py` 미들웨어 활용 가능).
    5.  유효한 키일 경우, 해당 파트너 정보(ID, 역할 등)를 컨텍스트에 저장하여 후속 로직에서 사용. 유효하지 않으면 401 Unauthorized 또는 403 Forbidden 에러 반환.
*   **키 관리:** 파트너는 `POST /partners/{partner_id}/api-keys` 엔드포인트를 통해 새 키를 발급받거나, 관리자 인터페이스를 통해 관리. 키 비활성화는 `DELETE /partners/{partner_id}/api-keys/{key_id}` 사용.

### 4.2. 주요 엔드포인트 (상세 예시)

*   **엔드포인트:** `POST /wallet/{player_id}/bet`
*   **설명:** 플레이어의 베팅을 처리하고 지갑 잔액을 차감합니다.
*   **라우터:** `backend/api/routers/wallet.py` 내 정의 예상.
*   **요청 본문 (Request Body - `schemas/wallet.py` 내 `BetRequest` 모델 예시):**
    ```json
    {
      "amount": 10.50, // 베팅 금액 (Decimal 또는 float)
      "currency": "USD", // 통화 코드 (ISO 4217)
      "game_id": "slots_game_001", // 게임 식별자
      "round_id": "round_abc123xyz", // 게임 라운드 식별자 (고유해야 함)
      "transaction_id_partner": "partner_tx_id_789" // 파트너 시스템의 고유 트랜잭션 ID (옵션, 중복 방지용)
    }
    ```
*   **성공 응답 (Success Response - `schemas/wallet.py` 내 `BetResponse` 모델 예시):**
    ```json
    {
      "transaction_id": "platform_tx_uuid_here", // 플랫폼에서 생성된 고유 트랜잭션 ID (UUID)
      "player_id": "player_uuid_here",
      "new_balance": 89.50, // 베팅 후 플레이어의 새 잔액
      "processed_at": "isoformat_datetime"
    }
    ```
*   **오류 응답 (Error Responses):**
    *   `400 Bad Request`: 요청 본문 유효성 오류, 잔액 부족 등.
        ```json
        {
          "detail": "Insufficient funds."
        }
        ```
    *   `401 Unauthorized / 403 Forbidden`: 유효하지 않은 API 키 또는 권한 부족.
    *   `404 Not Found`: 존재하지 않는 `player_id`.
    *   `409 Conflict`: 이미 처리된 `transaction_id_partner` (멱등성 보장 실패).
    *   `500 Internal Server Error`: 서버 내부 오류, 게임 제공사 API 연동 실패 등.

*(다른 엔드포인트들도 유사한 방식으로 요청/응답 스키마, 성공/오류 케이스를 상세히 정의해야 합니다.)*

## 5. 핵심 서비스 상세 (Core Service Details)

### 5.1. AML 서비스 (`backend/services/aml/aml_service.py`)

자금세탁방지(AML) 서비스는 플랫폼의 규정 준수 및 위험 관리에 중추적인 역할을 담당하며, 트랜잭션 데이터를 기반으로 의심스러운 활동을 식별합니다.

*   **실행 방식:**
    *   **비동기 이벤트 기반:** Kafka의 `wallet.transaction.created` 토픽을 구독하는 전용 컨슈머 그룹을 통해 실행되는 것이 주요 방식입니다. 이를 통해 지갑 서비스의 성능에 영향을 주지 않고 독립적으로 분석을 수행합니다. Celery 또는 Arq와 같은 Python 비동기 작업 큐를 사용하여 Kafka 컨슈머로부터 작업을 받아 처리할 수도 있습니다.
    *   **동기/API 기반:** 특정 시나리오(예: 특정 플레이어 재평가, 수동 조사)를 위해 API 엔드포인트(`api/routers/aml.py` 내 정의 예상)를 통한 직접적인 분석 요청도 지원될 수 있습니다.
*   **핵심 분석 로직 (`analyze_transaction` 및 하위 메서드):**
    *   **데이터 수집:** 분석 대상 트랜잭션 정보 외에, 플레이어의 과거 행동 패턴 비교를 위해 `WalletRepository`를 통해 관련 과거 트랜잭션(`_get_historical_transactions`) 및 플레이어 위험 프로필(`_get_or_create_risk_profile` - `aml_risk_profiles` 테이블)을 조회합니다.
    *   **위험 요소 평가:** 정의된 규칙 및 임계값(`self.thresholds`, `self.pattern_thresholds`)에 따라 개별 위험 요소를 평가합니다.
        *   **고액 거래:** 통화별 임계값 초과 시 +40점. 임계값은 `self.thresholds` 딕셔너리에 정의되어 쉽게 조정 가능.
        *   **시간 편차:** 과거 30일간의 거래 시간/요일 분포를 계산하여 활동량이 적거나(예: 상위 90% 활동량 미만) 전무한 시간대에 발생한 거래를 탐지. 정규 분포에서 벗어나는 정도를 점수화할 수도 있음 (현재는 Boolean).
        *   **금액 편차:** 과거 30일간 동일 유형 거래의 평균(μ) 및 표준편차(σ) 계산. 현재 금액(x)의 Z-score ((x - μ) / σ)가 설정된 임계값(예: 2.5) 초과 시 탐지. 표준편차가 0에 가까운 경우(거래 금액이 거의 동일한 경우) 작은 편차에도 민감하게 반응하도록 최소 표준편차(예: 0.01) 적용. 과거 거래 범위를 벗어나는 경우도 탐지.
        *   **빈도 편차:** 최근 24시간 거래 건수가 과거 7일/30일 일평균 건수 대비 급증(예: 3배 초과)하고, 절대 건수도 특정 기준(예: 3건 초과)을 넘는지 복합적으로 판단. 과거 데이터 부족 시(예: 주간/월간 평균 계산 불가 시) 분석 생략 또는 다른 기준 적용.
        *   **구조화 의심 거래 (Structuring):** (현재 명시적 구현은 없으나 추가될 수 있음) 짧은 기간(예: 24~48시간) 동안 보고 임계값 직전의 금액으로 여러 번 입금/출금하는 패턴 탐지.
        *   **자금 급속 이동 (Rapid Movement):** (현재 명시적 구현은 없으나 추가될 수 있음) 입금 후 짧은 시간(예: 24시간) 내에 게임 플레이 없이 대부분의 금액을 출금하는 패턴 탐지.
        *   **고위험 국가 연관:** (현재 `self.high_risk_countries` 목록만 존재, 실제 로직 추가 필요) 플레이어 등록 국가, 접속 IP 국가, 입출금 계좌 국가 등이 고위험 국가 목록에 포함되는지 확인.
        *   **외부 감시 목록 스크리닝 (Watchlist Screening):** (구현 시 고려) 플레이어 정보를 외부 제재 목록 또는 PEP(주요 정치적 인물) 목록 제공 업체의 API와 대조하여 일치 여부 확인.
    *   **위험 점수 계산:**
        *   개별 위험 요소별 기본 점수 할당.
        *   탐지된 행동 패턴 편차 종류 수에 따라 심각도(Severity, 0.0 ~ 1.0) 계산 후 가중 점수 부여 (예: `점수 += 25 * severity`).
        *   특정 위험 요소 조합이 발견되면 `_calculate_composite_risk`를 통해 추가 점수 부여 (최대 40점).
        *   최종 점수는 0점에서 100점 사이로 정규화.
    *   **결과 처리:** 계산된 점수 및 위험 요소에 따라 알림 생성 여부, 보고 필요 여부, 알림 유형/심각도 결정.
*   **플레이어 위험 프로필 (`AMLRiskProfile`):**
    *   플레이어별 위험도 및 거래 패턴을 지속적으로 추적 관리.
    *   `_update_risk_profile` 메서드를 통해 각 트랜잭션 분석 후 업데이트됨.
    *   단순히 마지막 점수를 덮어쓰는 것이 아니라, 기존 점수와 새 분석 점수를 가중 평균하여 점진적인 위험도 변화 반영 (예: `기존점수 * 0.7 + 새점수 * 0.3`).
    *   최근 7일/30일간의 입출금 횟수/금액, 마지막 거래/플레이 일시 등 통계 정보 업데이트.
    *   탐지된 위험 요소를 JSONB 필드(`risk_factors`)에 누적 기록 (요소 이름, 최초/최근 탐지 시각, 횟수, 상세 정보 등).
*   **알림 관리 (`AMLAlert`):**
    *   자동 생성된 알림 외에, 조사관이 수동으로 생성(`create_alert` API) 가능.
    *   알림 상태(`alert_status`: NEW, INVESTIGATING, CLOSED, REPORTED 등)는 API(`update_alert_status`)를 통해 관리.
    *   검토자, 검토 시간, 메모 등 조사 기록 저장 가능.

### 5.2. 지갑 서비스 (Wallet Service)

플레이어 자금의 입출금, 게임 관련 자금 이동을 안전하고 정확하게 처리합니다.

*   **핵심 모델:** `Wallet`, `Transaction`.
*   **주요 기능 상세:**
    *   **잔액 관리:**
        *   **다중 통화:** 플레이어별, 통화별로 `Wallet` 레코드를 가질 수 있음 (예: 플레이어 A의 USD 지갑, EUR 지갑). 또는 단일 레코드 내에 JSONB 등으로 통화별 잔액 저장. 스키마상으로는 전자가 더 명확해 보임 (플레이어ID, 파트너ID, 통화 조합).
        *   **정확성:** 모든 잔액 계산 및 저장 시 Python의 `Decimal` 타입과 PostgreSQL의 `NUMERIC` 타입 사용 필수. 부동소수점 오류 방지.
        *   **동시성 제어:**
            *   **비관적 락:** 입/출금/베팅 시 관련 `Wallet` 레코드에 `SELECT ... FOR UPDATE`를 사용하여 DB 레벨 락 설정. 다른 트랜잭션은 락이 해제될 때까지 대기. 데이터 정합성은 보장되나 동시 요청 시 병목 현상 발생 가능.
            *   **낙관적 락:** `Wallet` 테이블에 `version` 컬럼 추가. 업데이트 시 `WHERE version = expected_version` 조건을 포함하고 `version`을 1 증가. 업데이트 실패(다른 트랜잭션이 먼저 커밋한 경우) 시 재시도 로직 구현 필요. 더 높은 동시성을 제공할 수 있으나 구현 복잡도 증가. 현재 코드는 비관적 락 방식일 가능성이 높음.
    *   **트랜잭션 처리:**
        *   **원자성:** 각 입/출금/베팅/승리 처리는 단일 데이터베이스 트랜잭션 내에서 수행되어 중간 실패 시 롤백 보장.
        *   **멱등성 (Idempotency):** 파트너 시스템의 고유 ID(`transaction_id_partner`)를 `Transaction` 테이블에 저장하고 unique 제약 조건 설정. 동일 ID로 재요청 시 `409 Conflict` 에러를 반환하거나, 기존 처리 결과를 반환하여 중복 처리 방지. (Deposit, Withdrawal API에 필수적)
        *   **상태 관리:** `Transaction.status` 컬럼을 통해 거래의 생명주기 관리. 특히 외부 시스템(결제 게이트웨이, 게임 제공사) 연동이 필요한 경우 `PENDING`, `PROCESSING` 등의 중간 상태 활용. 완료 또는 실패 시 `COMPLETED`, `FAILED`, `CANCELED` 등으로 최종 상태 변경.
        *   **감사 추적:** 모든 자금 변동은 `Transaction` 테이블에 기록. 변경 전/후 잔액, 관련 게임/라운드 ID, 요청 메타데이터 등을 포함하여 문제 발생 시 원인 추적 용이.
    *   **비동기 처리 (출금):** 출금 요청은 내부 승인 절차나 외부 자금 이체 시스템 연동이 필요할 수 있음. 이 경우, API는 출금 요청 접수(상태: `PENDING` 또는 `PROCESSING`)만 처리하고 실제 처리는 백그라운드 워커나 별도 프로세스에서 비동기적으로 수행 후 상태 업데이트 및 Kafka 이벤트 발행 가능.

### 5.3. 게임 통합 서비스 (Game Integration Service)

외부 게임 제공사와의 연동을 담당하며, 플랫폼의 다른 서비스와 게임 제공사 API 사이의 브릿지 역할을 합니다.

*   **어댑터 패턴:** 각 게임 제공사별 API 연동 로직을 별도의 모듈/클래스로 구현. 새로운 제공사 추가 시 해당 어댑터만 구현하면 되도록 설계.
*   **OCasino API 연동 상세 (가정):**
    *   **프로토콜:** OCasino가 REST API를 제공한다고 가정. JSON 형식의 요청/응답 사용.
    *   **인증:** OCasino API 호출 시 필요한 인증 방식(API Key 헤더, OAuth2 토큰 등) 처리. 인증 정보는 `game_providers.api_credentials`에 안전하게 저장 및 관리.
    *   **API Wrapper:** Python `requests` 또는 `httpx` 라이브러리를 사용하여 OCasino API 호출 로직 구현. 타임아웃 설정, 예외 처리 포함.
        *   `get_game_list()`: 게임 목록 조회 API 호출 및 결과 파싱.
        *   `launch_game(player_id, game_id, ...)`: 게임 실행 URL/토큰 요청 API 호출.
        *   `process_bet(round_id, player_id, amount, ...)`: 베팅 처리 API 호출.
        *   `get_round_result(round_id)`: 라운드 결과 조회 API 호출 (폴링 방식).
    *   **결과 처리 (콜백 방식):** OCasino가 결과 발생 시 플랫폼의 특정 엔드포인트(예: `/games/callbacks/ocasino/round-result`)를 호출하도록 설정. 이 엔드포인트는 요청의 유효성(시그니처 검증 등) 확인 후, `Wallet Service`의 `record_win` 호출. 비동기 처리를 위해 수신 즉시 Kafka 이벤트 발행 후 백그라운드에서 처리하는 방식도 가능.
    *   **데이터 변환:** OCasino API의 데이터 형식(플레이어 식별 방식, 금액 단위, 상태 코드 등)을 플랫폼 내부 형식으로 변환. 반대의 경우도 마찬가지.
*   **견고성 및 안정성:**
    *   **재시도 로직:** 일시적인 네트워크 오류 또는 제공사 API 오류 발생 시 지수 백오프(Exponential Backoff)를 적용한 재시도 로직 구현 (예: `tenacity` 라이브러리 활용).
    *   **서킷 브레이커 (Circuit Breaker):** 특정 제공사 API의 실패율이 임계치를 초과하면 해당 API 호출을 일시적으로 차단하여 시스템 전체 부하 방지. 주기적으로 API 상태 확인 후 자동 복구. (예: `pybreaker` 라이브러리 활용).
    *   **캐싱:** 게임 목록, 제공사 정보 등 자주 변경되지 않는 데이터는 Redis 등에 캐싱하여 외부 API 호출 빈도 감소.
*   **세션 관리:** 플레이어의 게임 세션 정보(시작 시간, 활성 게임, 관련 토큰 등)를 Redis 또는 별도 테이블에 저장 및 관리하여 게임 중단/재개 등 지원 가능.

## 6. 데이터베이스 스키마 (Database Schema)

PostgreSQL 데이터베이스 스키마는 SQLAlchemy 모델(`backend/models/`)을 통해 정의됩니다.

### 6.1. 주요 테이블 구조 (상세)

*(기존 테이블에 예상되는 컬럼, 타입, 제약조건 추가)*

*   **`partners`**:
    *   `id` (UUID, PK)
    *   `name` (VARCHAR(100), NOT NULL)
    *   `type` (VARCHAR(20), NOT NULL, CHECK type IN ('operator', 'aggregator', 'affiliate'))
    *   `status` (VARCHAR(20), NOT NULL, DEFAULT 'active', CHECK status IN ('active', 'inactive', 'suspended'))
    *   `commission_rate` (NUMERIC(5, 4), NOT NULL, DEFAULT 0.0)
    *   `contact_email` (VARCHAR(255), UNIQUE)
    *   `registration_number` (VARCHAR(50), Nullable): 사업자 등록번호
    *   `address` (TEXT, Nullable)
    *   `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT now())
    *   `updated_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT now())
    *   *(Indexes: `type`, `status`)*
*   **`api_keys`**:
    *   `id` (SERIAL, PK)
    *   `key_prefix` (VARCHAR(10), NOT NULL, UNIQUE): 예: `sk_live_`
    *   `key_hash` (VARCHAR(255), NOT NULL)
    *   `partner_id` (UUID, NOT NULL, FK -> partners.id ON DELETE CASCADE)
    *   `status` (VARCHAR(20), NOT NULL, DEFAULT 'active', CHECK status IN ('active', 'inactive'))
    *   `scopes` (JSONB, Nullable): 허용된 권한 범위 (예: `["wallet:read", "wallet:write"]`)
    *   `expires_at` (TIMESTAMP WITH TIME ZONE, Nullable)
    *   `last_used_at` (TIMESTAMP WITH TIME ZONE, Nullable)
    *   `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT now())
    *   *(Indexes: `partner_id`, `status`)*
*   **`wallets`**:
    *   `id` (UUID, PK, DEFAULT gen_random_uuid())
    *   `player_id` (VARCHAR(255), NOT NULL)
    *   `partner_id` (UUID, NOT NULL, FK -> partners.id ON DELETE RESTRICT)
    *   `currency` (VARCHAR(3), NOT NULL)
    *   `balance` (NUMERIC(19, 4), NOT NULL, DEFAULT 0.0, CHECK balance >= 0)
    *   `version` (Integer, NOT NULL, DEFAULT 1): 낙관적 락을 위한 버전 컬럼 (선택적)
    *   `status` (VARCHAR(20), NOT NULL, DEFAULT 'active', CHECK status IN ('active', 'frozen'))
    *   `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT now())
    *   `updated_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT now())
    *   *(Indexes: `partner_id`, `status`)*
    *   *(Unique Constraint: (`player_id`, `partner_id`, `currency`))*
*   **`transactions`**:
    *   `id` (UUID, PK, DEFAULT gen_random_uuid())
    *   `wallet_id` (UUID, NOT NULL, FK -> wallets.id ON DELETE RESTRICT)
    *   `player_id` (VARCHAR(255), NOT NULL)
    *   `partner_id` (UUID, NOT NULL)
    *   `type` (VARCHAR(20), NOT NULL, CHECK type IN ('DEPOSIT', 'WITHDRAWAL', 'BET', 'WIN', 'ADJUSTMENT', 'COMMISSION', ...))
    *   `_encrypted_amount` (TEXT, NOT NULL): Base64 인코딩된 암호화된 금액 문자열
    *   `currency` (VARCHAR(3), NOT NULL)
    *   `balance_before` (NUMERIC(19, 4), Nullable): 거래 전 잔액 (감사 추적용)
    *   `balance_after` (NUMERIC(19, 4), Nullable): 거래 후 잔액 (감사 추적용)
    *   `status` (VARCHAR(20), NOT NULL, CHECK status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED', 'CANCELED'))
    *   `game_id` (VARCHAR(100), Nullable)
    *   `round_id` (VARCHAR(100), Nullable)
    *   `transaction_id_partner` (VARCHAR(255), Nullable)
    *   `ip_address` (VARCHAR(45), Nullable): 거래 요청 IP 주소
    *   `user_agent` (TEXT, Nullable): 거래 요청 User-Agent
    *   `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT now())
    *   `metadata` (JSONB, Nullable)
    *   *(Indexes: `wallet_id`, `player_id`, `partner_id`, `type`, `status`, `game_id`, `round_id`, `created_at`, (`transaction_id_partner`, `partner_id`) - 멱등성)*
    *   *(Partitioning: `created_at` 기준으로 월별 또는 일별 파티셔닝 고려)*
*   **`games`**:
    *   `id` (VARCHAR(100), PK)
    *   `provider_id` (Integer, NOT NULL, FK -> game_providers.id ON DELETE RESTRICT)
    *   `name` (VARCHAR(255), NOT NULL)
    *   `category` (VARCHAR(50))
    *   `rtp` (NUMERIC(5, 4), Nullable)
    *   `volatility` (VARCHAR(20), Nullable): 변동성 (low, medium, high)
    *   `features` (JSONB, Nullable): 게임 특징 (free spins, bonus rounds 등)
    *   `status` (VARCHAR(20), NOT NULL, DEFAULT 'active', CHECK status IN ('active', 'inactive', 'maintenance'))
    *   `launch_url_template` (TEXT, Nullable)
    *   `thumbnail_url` (TEXT, Nullable)
    *   `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT now())
    *   `updated_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT now())
    *   *(Indexes: `provider_id`, `category`, `status`)*
*   **`game_providers`**:
    *   `id` (SERIAL, PK)
    *   `name` (VARCHAR(100), NOT NULL, UNIQUE)
    *   `api_endpoint` (VARCHAR(255))
    *   `api_credentials` (TEXT): 암호화된 API 인증 정보
    *   `integration_type` (VARCHAR(50)): 연동 방식 식별자 (예: 'OCasino_v1', 'StandardAPI_v2')
    *   `status` (VARCHAR(20), NOT NULL, DEFAULT 'active', CHECK status IN ('active', 'inactive'))
    *   `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT now())
    *   `updated_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT now())
*   **`aml_alerts`**:
    *   `id` (SERIAL, PK)
    *   `player_id` (VARCHAR(255), NOT NULL)
    *   `partner_id` (UUID, NOT NULL)
    *   `transaction_id` (UUID, Nullable)
    *   `alert_type` (VARCHAR(50), NOT NULL)
    *   `alert_severity` (VARCHAR(20), NOT NULL)
    *   `alert_status` (VARCHAR(20), NOT NULL, DEFAULT 'NEW')
    *   `description` (TEXT)
    *   `risk_score` (Float)
    *   `risk_factors` (JSONB)
    *   `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT now())
    *   `assignee_id` (VARCHAR(100), Nullable): 담당 조사관 ID
    *   `reviewed_by` (VARCHAR(100), Nullable)
    *   `reviewed_at` (TIMESTAMP WITH TIME ZONE, Nullable)
    *   `review_notes` (TEXT, Nullable)
    *   `report_reference` (VARCHAR(100), Nullable): 관련 SAR 보고서 ID 등
    *   *(Indexes: `player_id`, `partner_id`, `transaction_id`, `alert_type`, `alert_severity`, `alert_status`, `created_at`)*
*   **`aml_risk_profiles`**:
    *   `id` (SERIAL, PK)
    *   `player_id` (VARCHAR(255), NOT NULL, UNIQUE)
    *   `partner_id` (UUID, NOT NULL)
    *   `overall_risk_score` (Float, NOT NULL, DEFAULT 30.0)
    *   ... (다양한 통계 컬럼) ...
    *   `is_pep` (Boolean, Nullable): 정치적 주요 인물 여부
    *   `is_sanctioned` (Boolean, Nullable): 제재 목록 포함 여부
    *   `risk_level` (VARCHAR(20), Nullable): 계산된 위험 등급 (low, medium, high)
    *   `risk_factors` (JSONB)
    *   `last_assessment_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT now())
    *   `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT now())
    *   *(Indexes: `partner_id`, `overall_risk_score`, `risk_level`)*
*   **`ip_whitelist`**:
    *   `id` (SERIAL, PK)
    *   `partner_id` (UUID, NOT NULL, FK -> partners.id ON DELETE CASCADE)
    *   `ip_address` (CIDR): 허용 IP 주소 또는 CIDR 블록 (PostgreSQL의 `CIDR` 타입 활용)
    *   `description` (VARCHAR(255), Nullable)
    *   `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT now())
    *   *(Unique Constraint: (`partner_id`, `ip_address`))*

### 6.2. 데이터베이스 고려사항

*   **인덱싱:** 위에 명시된 인덱스 외에도, 자주 사용되는 조회 조건(WHERE절), 정렬 조건(ORDER BY), 조인 조건(JOIN ON)에 해당하는 컬럼에 적절한 인덱스(B-tree, GIN 등) 생성 필요. 복합 인덱스 고려.
*   **파티셔닝:** `transactions` 테이블과 같이 시간이 지남에 따라 매우 커질 수 있는 테이블은 `created_at` 컬럼을 기준으로 범위(Range) 파티셔닝 또는 리스트(List) 파티셔닝 적용 고려. 조회 성능 향상 및 데이터 관리(오래된 파티션 삭제/아카이빙) 용이성 확보.
*   **뷰 (Views):** 복잡한 조인이나 집계가 필요한 보고서용 데이터를 위해 데이터베이스 뷰 또는 Materialized View 생성 고려.
*   **데이터 타입:** 금액은 `NUMERIC`, 날짜/시간은 `TIMESTAMP WITH TIME ZONE`, JSON 데이터는 `JSONB`, IP 주소는 `INET` 또는 `CIDR` 등 적절한 데이터 타입 사용.
*   **제약 조건:** `NOT NULL`, `UNIQUE`, `CHECK`, `FOREIGN KEY` 등 제약 조건을 명확히 설정하여 데이터 무결성 강화.

## 7. 보안 (Security)

### 7.1. IP 화이트리스팅

*   **적용 대상:** 주로 파트너 시스템에서 플랫폼 API를 호출하는 경우 적용. 특정 파트너는 화이트리스트 사용을 선택적으로 활성화/비활성화 가능하도록 설정(`partners` 테이블에 플래그 추가 등).
*   **구현 상세:** 미들웨어는 요청 IP를 확인하고, `partner_id`에 해당하는 `ip_whitelist` 목록과 매칭. CIDR 블록을 지원하여 IP 범위 지정 가능. `X-Forwarded-For` 헤더를 신뢰할지 여부 설정 중요 (신뢰할 수 있는 프록시 뒤에 있는 경우).

### 7.2. API 키 관리 및 인증/권한 부여

*   **키 보안:**
    *   **파트너 책임:** 파트너는 발급받은 API 키를 안전하게 보관해야 함을 명확히 안내. 코드 저장소 등에 직접 커밋하지 않도록 경고.
    *   **키 교체:** 정기적인 API 키 교체 권장 및 지원. 파트너가 이전 키 만료 기간을 두고 새 키를 발급받아 원활하게 전환할 수 있는 기능 제공.
    *   **유출 시:** 키 유출 의심 시 즉시 비활성화(`DELETE /.../api-keys/{key_id}`) 할 수 있는 기능 제공.
*   **권한 부여 (Scopes):**
    *   API 키 생성 시 또는 이후에 해당 키로 접근 가능한 범위를 제한하는 '스코프(Scope)' 설정 기능 구현 고려. (예: 특정 키는 잔액 조회(`wallet:read`)만 가능, 다른 키는 입출금(`wallet:write`)까지 가능).
    *   FastAPI의 `Security` 의존성 시스템과 연계하여 각 엔드포인트에 필요한 스코프를 정의하고, 요청 컨텍스트의 API 키가 해당 스코프를 가졌는지 검증.

### 7.3. 데이터 암호화

*   **대상:** `transactions._encrypted_amount`, `game_providers.api_credentials`, 잠재적으로 `partners` 테이블의 민감 정보(주소, 연락처 등 PII).
*   **AES-GCM 상세:**
    *   **키 길이:** 256비트 (32바이트) 권장. `ENCRYPTION_KEY` 환경 변수는 Base64 인코딩된 32바이트 키.
    *   **Nonce:** 암호화 시마다 고유한 Nonce(Number used once) 생성 필수. 일반적으로 12바이트(96비트) 사용. 생성된 Nonce는 암호화된 데이터와 함께 저장되어야 복호화 가능.
    *   **Tag:** GCM 모드는 인증 태그(Authentication Tag)를 생성하여 데이터 무결성 및 인증 보장. 이 태그도 Nonce와 함께 저장 필요.
    *   **저장 형식 (예시):** Base64 인코딩된 문자열로 결합하여 저장. 예: `base64(nonce) + "." + base64(tag) + "." + base64(ciphertext)`
    *   **복호화:** 저장된 문자열에서 Nonce, Tag, Ciphertext 분리 후 `decrypt_aes_gcm` 수행. Tag 검증 실패 시 복호화 실패 처리.
*   **키 관리 시스템:** 운영 환경에서는 환경 변수보다 HashiCorp Vault, AWS Secrets Manager, Google Secret Manager 등 전문 비밀 관리 솔루션 사용 권장. 애플리케이션이 시작 시 또는 필요 시 안전하게 키를 가져오도록 구성. 키 교체(Rotation) 기능 지원 활용.

### 7.4. 일반 보안 강화

*   **HTTPS 강제:** 모든 API 통신은 TLS/SSL(HTTPS)을 통해 암호화. 로드 밸런서 또는 Ingress 레벨에서 TLS 종료 처리.
*   **입력 유효성 검사:** Pydantic을 통한 자동 유효성 검사 외에도, SQL Injection, Cross-Site Scripting (XSS) 등 잠재적 공격을 방지하기 위해 모든 외부 입력(쿼리 파라미터, 경로 파라미터, 요청 본문)에 대한 추가적인 검증 및 이스케이프 처리 수행.
*   **의존성 관리:** `requirements.txt` 또는 `pyproject.toml`에 명시된 라이브러리들의 보안 취약점 정기적 스캔 (예: `safety`, `pip-audit`, Snyk, GitHub Dependabot). 발견 시 즉시 업데이트 또는 완화 조치.
*   **속도 제한 (Rate Limiting):** Brute-force 공격 및 서비스 남용 방지를 위해 API 엔드포인트별, 파트너별(API 키 기준), IP 주소별 속도 제한 적용 (`backend/middlewares/rate_limit_middleware.py`, Redis 활용). 고정 윈도우, 슬라이딩 윈도우 등 다양한 전략 적용 가능.
*   **CORS 정책:** FastAPI 설정에서 Cross-Origin Resource Sharing (CORS) 정책을 명확히 설정하여 허용된 출처(Origin)에서만 프론트엔드 접근 허용. (`allow_origins` 설정).
*   **보안 헤더:** 응답 헤더에 `Strict-Transport-Security`, `X-Content-Type-Options`, `X-Frame-Options` 등 보안 관련 헤더 추가하여 브라우저 레벨 보안 강화.
*   **정기 보안 감사:** 외부 전문 업체를 통한 정기적인 모의 해킹 및 보안 취약점 진단 수행.

## 8. 배포 및 운영 (Deployment & Operations)

### 8.1. Docker 및 Kubernetes 설정 (상세)

*   **이미지 최적화:** Python 서비스의 경우, 가상 환경 사용 및 `pip install --no-cache-dir` 옵션 활용. Multi-stage build를 통해 최종 이미지에는 런타임에 필요한 최소한의 의존성만 포함시켜 이미지 크기 축소 및 보안 강화.
*   **Kubernetes 리소스 상세:**
    *   **`Deployment`:** `spec.strategy.type: RollingUpdate` 설정, `maxUnavailable`, `maxSurge` 파라미터 조정하여 무중단 배포 지원.
    *   **Health Checks:**
        *   `livenessProbe`: 컨테이너가 살아있는지 주기적 확인 (예: 간단한 HTTP GET 요청). 실패 시 컨테이너 재시작.
        *   `readinessProbe`: 컨테이너가 요청을 처리할 준비가 되었는지 확인 (예: DB 연결 확인, 필수 초기화 완료 확인). 실패 시 `Service` 로드 밸런싱 대상에서 제외.
    *   **Resource Management:** 각 컨테이너에 `resources.requests` (최소 보장 자원) 및 `resources.limits` (최대 사용 가능 자원) 설정. CPU 및 메모리 사용량 제한하여 노드 안정성 확보 및 리소스 예측 가능성 증대.
    *   **Autoscaling:**
        *   `HorizontalPodAutoscaler (HPA)`: CPU 또는 메모리 사용량, 커스텀 메트릭(예: Kafka Consumer Lag, 초당 요청 수) 기반으로 Deployment의 Pod 레플리카 수를 자동으로 조절.
        *   `Cluster Autoscaler`: HPA에 의해 Pod 수가 증가했으나 배치할 노드가 부족할 경우, 클라우드 제공사와 연동하여 Worker Node 수를 자동으로 늘림.
    *   **Storage:** PostgreSQL, Kafka 등 상태 저장 애플리케이션을 위해 클라우드 제공사의 관리형 블록 스토리지(예: AWS EBS, GCP Persistent Disk)를 사용하는 `StorageClass` 정의 및 `PersistentVolumeClaim`을 통해 동적 볼륨 프로비저닝. 백업 및 복구 전략 필수.
    *   **Network Policies:** Kubernetes `NetworkPolicy` 리소스를 사용하여 Pod 간 통신 제어. 기본적으로 모든 통신을 차단하고 필요한 서비스 간의 통신만 명시적으로 허용하여 네트워크 보안 강화 (Zero Trust Network).
*   **Helm/Kustomize 활용:**
    *   서비스별 Helm 차트 작성 또는 Kustomize 구성 파일 작성.
    *   환경별(개발, 스테이징, 운영) 설정 값 분리 (`values.yaml` 또는 Kustomize 오버레이).
    *   CI/CD 파이프라인에서 `helm upgrade --install` 또는 `kubectl apply -k` 명령어를 사용하여 배포 자동화.

### 8.2. 로깅 및 모니터링 전략 (상세)

*   **로깅:**
    *   **로그 레벨:** 운영 환경에서는 `INFO` 레벨 이상 로깅 기본 설정. 디버깅 필요 시 특정 서비스의 로그 레벨 동적 변경 기능 구현 고려 (예: `ConfigMap` 변경 또는 API 호출).
    *   **구조화된 로깅 (JSON):** `python-json-logger` 등의 라이브러리 사용. 포함 필드 예시: `@timestamp`, `level`, `service_name`, `trace_id`, `span_id`, `user_id`, `partner_id`, `message`, `exception_info` (에러 발생 시).
    *   **로그 수집 에이전트:** Fluentd/Fluent Bit DaemonSet으로 각 노드에 배포. Kubernetes 메타데이터(Pod 이름, 네임스페이스 등) 자동 태깅 설정.
    *   **중앙 저장소:** Elasticsearch 또는 Loki 사용. 로그 보존 기간 정책 설정 (예: 운영 로그 30일, 감사 로그 1년).
*   **모니터링:**
    *   **주요 모니터링 지표:**
        *   **API 게이트웨이/FastAPI:** 요청/응답 수 (HTTP 상태 코드별), 응답 시간 (평균, 95/99 백분위수), 오류율.
        *   **데이터베이스 (PostgreSQL):** 연결 수, 활성/대기 쿼리, 복제 지연 시간, CPU/메모리/디스크 사용률, 느린 쿼리(Slow Queries).
        *   **캐시 (Redis):** 메모리 사용률, 캐시 히트/미스 비율, 연결 수, 응답 시간.
        *   **메시지 큐 (Kafka):** 브로커 상태, 토픽별 메시지 수/크기, 컨슈머 랙(Lag), 요청 지연 시간.
        *   **AML Service:** 처리된 트랜잭션 수, 분석 소요 시간, 생성된 알림 수 (심각도별).
        *   **Wallet Service:** 처리된 입/출금/베팅/승리 건수, 평균 처리 시간, 오류 발생률.
    *   **대시보드 (Grafana):**
        *   **전체 시스템 상태 대시보드:** 주요 서비스 상태, 리소스 사용률, 핵심 비즈니스 지표(가입자, 활성 사용자, 총 거래량 등) 개요.
        *   **서비스별 상세 대시보드:** 각 마이크로서비스의 성능 지표, 리소스 사용량, 연관된 인프라(DB, Kafka 등) 지표 표시.
        *   **오류 추적 대시보드:** 시간별 오류 발생률, 서비스별/엔드포인트별 오류 분포, 특정 오류 로그 바로가기 링크.
    *   **분산 추적 (Jaeger/Tempo):** 요청이 여러 서비스를 거치는 과정 시각화. 각 단계(Span)별 소요 시간 확인하여 병목 구간 식별. 특정 Trace ID로 관련 로그 필터링 연동.
    *   **알림 (Alertmanager):**
        *   **규칙 예시:** "API 응답 시간 99백분위수가 1초를 5분간 초과", "HTTP 5xx 오류율 1% 초과", "Kafka 컨슈머 랙 1000 이상 10분간 지속", "DB 디스크 사용률 85% 초과".
        *   **알림 채널:** Slack (일반 알림), PagerDuty (긴급 알림) 등 역할/심각도에 따라 채널 분리.
        *   **Silence/Inhibition:** 계획된 점검 시간 동안 알림 음소거 또는 관련 알림 간의 중복 방지 설정.
*   **중앙 설정 관리:** 로깅/모니터링 에이전트(Fluent Bit, Prometheus Exporter 등)의 설정을 `ConfigMap` 등을 통해 중앙에서 관리하고, 변경 사항을 재배포 없이 적용할 수 있는 메커니즘 고려 (예: sidecar 컨테이너 활용).
*   **합성 모니터링 (Synthetic Monitoring):** 주기적으로 주요 API 엔드포인트 호출 또는 사용자 시나리오(로그인-베팅-잔액확인 등)를 시뮬레이션하여 기능 및 성능 이상 조기 감지.


## 9. 개선 가능 영역

현재 기술 문서는 플랫폼의 전반적인 구조와 핵심 기능을 설명하고 있지만, 더욱 견고하고 효율적인 시스템 운영 및 개발을 위해 다음과 같은 영역에서 보완 및 구체화가 필요합니다.

### 9.1. 테스트 전략 보완

현재 문서에는 테스트 실행(`pytest`)에 대한 언급은 있으나, 포괄적이고 체계적인 테스트 전략이 명확히 기술되어 있지 않습니다. 고품질 소프트웨어 제공 및 안정적인 운영을 위해 다음 테스트 레벨에 대한 구체적인 전략 수립 및 문서화가 필요합니다.

*   **단위 테스트 (Unit Tests):**
    *   **목표:** 개별 함수, 메서드, 클래스 등 가장 작은 코드 단위의 논리적 정확성 검증. 외부 의존성(DB, 외부 API, 다른 서비스, Kafka 등)은 철저히 모킹(Mocking)하여 테스트 대상 코드를 격리.
    *   **도구:** `pytest`, `unittest.mock`, `pytest-mock`.
    *   **범위:** 핵심 비즈니스 로직, 유틸리티 함수, 복잡한 계산 로직, 경계값(Edge case) 및 오류 처리 로직 집중 검증. **현재 `tests` 하위 디렉토리에 구현된 서비스 기능들에 대한 단위 테스트는 완료 및 디버깅되었습니다.**
    *   **위치:** 각 서비스 또는 모듈 내 `tests/unit` 또는 `tests/services` 디렉토리 구조 권장.
    *   **지표:** 코드 커버리지(Code Coverage) 측정 (`pytest-cov` 활용). 목표 커버리지(예: 85% 이상) 설정 및 CI 파이프라인에서 검증. **현재 핵심 기능 위주 테스트로 전체 커버리지는 약 30% 수준이지만, 중요 서비스의 테스트 커버리지는 지속적으로 개선될 예정입니다.**
*   **통합 테스트 (Integration Tests):**
    *   **목표:** 여러 컴포넌트(주로 서비스 내부 모듈 또는 서비스 간 연동)가 함께 동작할 때의 상호작용 및 데이터 흐름 검증.
    *   **범위:**
        *   서비스 내부: 서비스 로직 - 리포지토리 - DB 간 연동 테스트.
        *   서비스 간: API 호출 및 응답 계약 준수 여부, Kafka 메시지 발행/구독 연동 테스트.
    *   **환경:** 실제 DB(테스트용 DB 스키마 분리), Redis, Kafka 인스턴스를 Docker Compose 또는 testcontainers를 사용하여 테스트 환경 내 실행. 실제 외부 API 대신 모의 API 서버 활용 가능.
    *   **위치:** `tests/integration` 디렉토리 구조 권장.
*   **End-to-End (E2E) 테스트:**
    *   **목표:** 실제 사용자 또는 파트너 시스템 관점에서 주요 비즈니스 워크플로우(시나리오)가 전체 시스템을 거쳐 정상적으로 동작하는지 검증.
    *   **시나리오 예시:**
        *   파트너 등록 -> API 키 발급 -> API 호출 인증 성공.
        *   플레이어 입금 -> 게임 세션 시작 -> 베팅 -> 승리 -> 잔액 확인 -> 출금.
    *   **환경:** 실제 배포된 환경(가급적 스테이징 환경)을 대상으로 실행.
    *   **도구:** API 테스트 자동화 도구 (예: `pytest` + `httpx`, Postman/Newman 스크립트), 또는 UI가 있다면 관련 E2E 테스트 프레임워크 (Cypress, Playwright).
    *   **위치:** `tests/e2e` 디렉토리 구조 권장.
*   **계약 테스트 (Contract Testing - 마이크로서비스 환경에 강력 추천):**
    *   **목표:** 서비스 간의 API 계약(요청/응답 구조)이 깨지지 않도록 보장. 각 서비스를 독립적으로 테스트/배포 가능하게 지원.
    *   **도구:** Pact, Spring Cloud Contract (JVM).
    *   **방식:** Consumer(API 호출 측)가 기대하는 요청/응답 구조를 'Pact 파일'로 정의. Provider(API 제공 측)는 이 Pact 파일을 검증하여 계약 준수 여부 확인. CI 파이프라인에 통합.
*   **성능/부하 테스트 (Performance/Load Testing):**
    *   **목표:** 예상되는 트래픽 또는 그 이상의 부하 상황에서 시스템의 응답 시간, 처리량(Throughput), 리소스 사용률 등 성능 측정 및 병목 구간 식별.
    *   **도구:** k6, Locust, JMeter.
    *   **실행:** 정기적으로(예: 매 릴리즈 전) 프로덕션과 유사한 스테이징 환경에서 실행. 다양한 부하 시나리오(점진적 증가, 최대 부하 유지 등) 테스트.
*   **보안 테스트 (Security Testing):**
    *   **정적 분석 (SAST):** 코드 레벨의 보안 취약점 스캔 (예: Bandit, Semgrep). CI 파이프라인 통합.
    *   **동적 분석 (DAST):** 실행 중인 애플리케이션 대상 웹 취약점 스캔 (예: OWASP ZAP). 스테이징 환경 대상 실행.
    *   **의존성 검사:** 알려진 보안 취약점이 있는 라이브러리 사용 여부 검사 (예: `safety`, `pip-audit`, Snyk, Dependabot). CI 파이프라인 통합.
    *   **모의 해킹 (Penetration Testing):** 정기적으로 외부 전문 업체를 통해 실제 공격 시나리오 기반의 취약점 점검 수행.
*   **테스트 데이터 관리:** 각 테스트 레벨(특히 통합, E2E)에 필요한 일관성 있고 현실적인 테스트 데이터 생성 및 관리 전략 필요. 민감 데이터는 익명화 또는 마스킹 처리 필수.

### 9.2. CI/CD 파이프라인 상세화

문서에는 CI/CD 도구 사용 가능성이 언급되어 있지만, 실제 파이프라인 구성 및 단계별 상세 동작에 대한 설명이 부족합니다. 효과적인 자동화 및 빠른 배포 주기를 위해 다음과 같은 구체적인 파이프라인 정의가 필요합니다.

*   **파이프라인 트리거:**
    *   Git Feature 브랜치로 푸시: Linting, Unit Test 실행.
    *   Pull Request 생성/업데이트 (`develop` 또는 `main` 브랜치 대상): Linting, Unit Test, Integration Test 실행. 코드 리뷰 요청.
    *   `develop` 브랜치로 병합: 위 테스트 + Docker 이미지 빌드/푸시 + Staging 환경 자동 배포 + E2E 테스트 실행.
    *   `main` 브랜치로 병합 (또는 Git Tag 생성): 위 테스트 + Docker 이미지 빌드/푸시 (릴리즈 태그) + (선택적 수동 승인) + Production 환경 자동 배포 (Canary 또는 Blue/Green) + 배포 후 검증.
*   **주요 스테이지 상세:**
    1.  **코드 검증 (Validate):** 코드 체크아웃, Linting (Flake8, Black), 정적 분석 (MyPy, Bandit).
    2.  **단위 테스트 (Unit Test):** `pytest` 실행, 코드 커버리지 측정 및 보고서 생성/업로드. 커버리지 임계값 미달 시 파이프라인 실패.
    3.  **빌드 (Build):** 각 서비스별 `Dockerfile`을 사용하여 Docker 이미지 빌드. Git Commit SHA 및 브랜치/태그 정보로 이미지 태깅. Container Registry(ECR, GCR, Docker Hub 등)에 이미지 푸시.
    4.  **통합 테스트 (Integration Test):** Docker Compose 또는 testcontainers로 DB, Redis, Kafka 등 실행. `pytest`로 통합 테스트 실행.
    5.  **스테이징 배포 (Deploy Staging):** Helm 또는 Kustomize를 사용하여 빌드된 이미지를 Kubernetes Staging 클러스터에 배포.
    6.  **E2E 테스트 (E2E Test):** 스테이징 환경 대상으로 E2E 테스트 스크립트 실행.
    7.  **(선택) 수동 승인 (Manual Approval):** 운영 배포 전 최종 검토 및 승인 단계. (릴리즈 관리자와 연계).
    8.  **운영 배포 (Deploy Production):**
        *   **Canary Deployment:** 새로운 버전의 Pod를 소수(예: 5%)만 배포하여 실제 트래픽 일부를 흘려보냄. 모니터링 지표(오류율, 응답 시간 등) 확인 후 점진적으로 트래픽 전환 비율 증가 또는 롤백.
        *   **Blue/Green Deployment:** 현재 운영 중인 환경(Blue)과 동일한 구성의 새 환경(Green)에 새 버전 배포. 테스트 완료 후 로드 밸런서에서 트래픽을 Green으로 일괄 전환. 문제 발생 시 Blue로 즉시 롤백 가능.
    9.  **배포 후 검증 (Post-Deploy Verify):** 운영 환경에서 기본적인 API 호출(Health Check 등) 및 핵심 기능 스모크 테스트 수행. 초기 모니터링 대시보드 확인.
*   **도구 체인 (예시):** GitLab CI/CD 또는 GitHub Actions (파이프라인 정의/실행) + Docker (이미지 빌드) + AWS ECR (컨테이너 레지스트리) + Helm (Kubernetes 패키징) + Argo CD (Kubernetes GitOps 배포) + Prometheus/Grafana (모니터링) + Snyk (보안 스캔).
*   **보안:** CI/CD 파이프라인 자체의 보안 강화. 빌드/배포 단계에서 필요한 비밀 정보(DB 접속 정보, 클라우드 자격 증명 등)는 Vault 연동 또는 CI/CD 플랫폼의 보안 비밀 관리 기능 사용. 이미지 서명 및 검증(예: Notary, Sigstore) 도입 고려.

### 9.3. 장애 복구 전략 (Disaster Recovery)

현재 문서에는 인프라 구성 요소만 나열되어 있을 뿐, 실제 장애 발생 시 복구 목표와 절차에 대한 구체적인 계획이 부족합니다. 비즈니스 연속성을 위해 다음과 같은 명확한 전략 정의가 필수적입니다.

*   **복구 목표 정의 (RPO/RTO):**
    *   서비스별 중요도 분류 (Tier 1: Wallet, Auth / Tier 2: Game Integration, Partner / Tier 3: Reporting, AML 등).
    *   Tier별 목표 RPO (최대 허용 데이터 손실량 - 예: Tier 1: 5분, Tier 2: 1시간) 및 RTO (최대 허용 복구 시간 - 예: Tier 1: 30분, Tier 2: 2시간) 설정 및 합의.
*   **데이터 백업 및 복원:**
    *   **PostgreSQL:**
        *   클라우드 제공사 관리형 서비스(RDS, Cloud SQL 등) 사용 시 자동 백업 및 PITR(Point-in-Time Recovery) 기능 활용. 백업 주기(예: 매일) 및 보존 기간(예: 30일) 설정.
        *   직접 운영 시 `pg_basebackup` + WAL 아카이빙 구성하여 PITR 구현. 백업 파일은 다른 AZ 또는 Region의 S3 등 안전한 곳에 저장.
        *   정기적인 복원 테스트 필수 (예: 분기별).
    *   **Redis:** 사용 목적(캐시 vs. 영구 데이터)에 따라 RDB 스냅샷 또는 AOF 설정. 백업 파일 외부 저장 고려. 캐시는 복구 시 DB로부터 다시 로드 가능하므로 백업 중요도 낮을 수 있음.
    *   **Kafka:** 토픽별 리플리케이션 팩터(Replication Factor)를 3 이상으로 설정하고, 브로커를 여러 AZ에 분산 배치하여 내구성 확보. MirrorMaker 등을 이용한 클러스터 간 데이터 복제(DR용) 고려.
*   **인프라 복구:**
    *   **Multi-AZ 아키텍처:** Kubernetes 클러스터 노드, 관리형 DB/Cache/MQ 인스턴스를 최소 2개 이상의 AZ에 분산 배치. AZ 장애 시 다른 AZ의 리소스로 서비스 지속.
    *   **Infrastructure as Code (IaC):** Terraform 또는 CloudFormation 등을 사용하여 전체 인프라 구성을 코드로 관리. 이를 통해 다른 Region에 동일한 환경을 신속하게 재구성 가능.
    *   **컨테이너 레지스트리 가용성:** 사용 중인 레지스트리가 리전 장애 시에도 접근 가능한지 확인 (예: Multi-region 레지스트리 사용).
*   **애플리케이션 복구:**
    *   Kubernetes의 자동 복구 기능(Pod 재시작, 노드 장애 시 다른 노드에 스케줄링) 활용.
    *   상태 저장 애플리케이션(`StatefulSet`)의 경우 볼륨 재연결 및 데이터 복구 절차 명확화.
*   **장애 복구 계획 (DRP) 문서화:**
    *   장애 시나리오별(단일 노드 장애, AZ 장애, 리전 장애, 데이터 손상 등) 대응 절차 상세 기술.
    *   비상 연락망, 역할 및 책임(RACI) 정의.
    *   복구 절차 검증을 위한 정기적인 DR 드릴 계획 및 결과 기록.

### 9.4. 데이터 마이그레이션 계획

데이터베이스 스키마 변경은 운영 중인 서비스에 큰 영향을 줄 수 있으므로, 안전하고 예측 가능한 마이그레이션 전략이 필수적입니다.

*   **도구:** Alembic 사용 권장. 마이그레이션 스크립트는 코드와 함께 버전 관리 (`git`).
*   **프로세스:**
    1.  **스크립트 작성 및 검토:** 개발자가 로컬에서 `alembic revision --autogenerate` 실행 후 생성된 스크립트 검토 및 수정. 동료 개발자 코드 리뷰 필수.
    2.  **테스트:** 로컬 및 CI 환경에서 마이그레이션 적용(`alembic upgrade head`) 및 롤백(`alembic downgrade -1`) 테스트 수행. Staging 환경에서 프로덕션 데이터 복제본(민감 정보 제거)으로 테스트하여 성능 영향 및 데이터 정합성 검증.
    3.  **배포 전략 (Zero-Downtime 목표):**
        *   **단계 1: 비파괴적 스키마 변경 적용:** 새 테이블 생성, 새 컬럼 추가(NULL 허용 또는 DEFAULT 값 지정) 등 기존 코드와 호환되는 스키마 변경 먼저 적용. `alembic upgrade head` 실행.
        *   **단계 2: 애플리케이션 배포 (호환 코드):** 새 스키마를 인지하고 사용하는(하지만 이전 스키마도 처리 가능한) 애플리케이션 코드 배포. 예: 새 컬럼에 데이터 쓰기 시작, 읽기는 양쪽 모두 가능하게 처리.
        *   **단계 3 (필요시): 데이터 백필:** 새 컬럼에 기존 데이터를 채워 넣어야 하는 경우, 별도의 스크립트나 백그라운드 작업을 통해 데이터 마이그레이션 수행. 서비스 부하 고려하여 배치 처리 또는 점진적 수행.
        *   **단계 4: 애플리케이션 배포 (새 스키마 전용):** 이제 새 스키마만 사용하는 애플리케이션 코드 배포. 이전 스키마 관련 코드 제거.
        *   **단계 5: 파괴적 스키마 변경 적용:** 이전 컬럼 삭제, 테이블 이름 변경 등 호환되지 않는 변경 사항 적용. `alembic upgrade head` (해당 변경 스크립트). 이 단계는 롤백이 어려울 수 있으므로 신중하게 진행하고 사전 백업 필수.
*   **주의사항:**
    *   **긴 트랜잭션 방지:** 대용량 데이터 마이그레이션은 DB 락(lock)을 유발할 수 있으므로, 작은 배치 단위로 나누어 커밋 간격을 짧게 가져감.
    *   **온라인 스키마 변경 도구:** 매우 큰 테이블의 경우, `pt-online-schema-change` (Percona Toolkit) 또는 `gh-ost` (GitHub) 와 같은 도구를 사용하여 서비스 중단 없이 스키마 변경 고려 (PostgreSQL에서는 적용이 제한적일 수 있음, `pg_repack` 등 고려).
    *   **롤백 계획:** 각 마이그레이션 단계별 롤백 절차 명확화. Alembic의 `downgrade` 기능 활용 또는 특정 시점 백업 복구 계획.

### 9.5. 캐싱 전략 구체화

Redis를 활용한 캐싱은 성능 향상에 중요하지만, 잘못 관리하면 데이터 불일치나 성능 저하를 유발할 수 있습니다. 다음 사항들을 구체화해야 합니다.

*   **캐시 대상 선정 기준:**
    *   읽기 빈도가 쓰기 빈도보다 현저히 높은 데이터.
    *   생성 비용(계산 비용, DB 조회 비용)이 높은 데이터.
    *   약간의 데이터 지연(staleness)을 허용할 수 있는 데이터 (TTL 기반 캐시의 경우).
*   **캐시 키 전략:**
    *   일관성 있는 네이밍 규칙 적용 (예: `<service>:<type>:<id>:<sub_id>`).
    *   키 충돌 방지 및 예측 가능한 키 생성 로직.
*   **캐시 무효화 (Invalidation):**
    *   **TTL 기반:** 가장 간단하며 기본 전략. 데이터 종류별 적절한 TTL 설정 (예: 게임 목록 - 1시간, 파트너 설정 - 5분, 실시간 잔액 - 캐시 부적합 또는 매우 짧은 TTL).
    *   **이벤트 기반 (Explicit Invalidation):** 데이터 원본(DB) 변경 시 관련 이벤트를 Kafka 등으로 발행. 해당 이벤트를 구독하는 서비스가 Redis의 관련 캐시 키 삭제/갱신. 데이터 정합성은 높으나 구현 및 관리 복잡도 증가. (예: `partner.updated` 이벤트 수신 시 `partner:setting:{partner_id}` 키 삭제).
    *   **Read-Through / Write-Through 패턴:** 캐싱 라이브러리나 프레임워크가 제공하는 기능 활용 고려. 애플리케이션 코드는 캐시와만 상호작용하고, 캐시 라이브러리가 DB 동기화 및 무효화 처리.
*   **데이터 직렬화:** Python 객체를 Redis에 저장하기 위한 직렬화 방식 선택.
    *   **JSON:** 사람이 읽기 쉽고 언어 간 호환성 좋음. 객체 타입 정보 손실 가능성. `datetime`, `Decimal` 등 직렬화/역직렬화 처리 필요.
    *   **Pickle:** Python 객체 구조 그대로 저장 가능. 편리하지만 보안 위험(임의 코드 실행 가능성) 및 다른 언어와의 호환성 문제. 사용 지양 권장.
    *   **MessagePack:** JSON보다 효율적인 바이너리 직렬화 포맷.
*   **캐시 클러스터링/고가용성:** 단일 Redis 인스턴스는 SPOF(Single Point of Failure)가 될 수 있음.
    *   **Redis Sentinel:** 마스터-슬레이브 복제 구성 및 자동 장애 감지/페일오버 제공.
    *   **Redis Cluster:** 데이터 샤딩(Sharding)을 통해 수평적 확장성 및 고가용성 제공.
    *   클라우드 제공사의 관리형 Redis 서비스(ElastiCache, Memorystore 등) 사용 시 고가용성 구성 용이.
*   **모니터링:** Redis 전용 모니터링 도구 또는 Prometheus `redis-exporter`를 사용하여 메모리 사용량, 키 개수, 초당 명령 수, 연결 수, 캐시 히트율, 지연 시간, 제거된 키(Evicted Keys) 수 등 주요 지표 모니터링. 히트율이 낮거나 제거되는 키가 많으면 캐시 크기 또는 전략 재검토 필요.
