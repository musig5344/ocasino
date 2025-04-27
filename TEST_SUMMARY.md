# 테스트 완료 현황

이 문서는 `tests` 디렉토리 내 테스트 파일들이 검증하는 기능들을 요약합니다. 모든 명시된 테스트는 완료 및 디버깅되었습니다.

## 테스트 환경 설정 (`tests/conftest.py`)

*   테스트 실행 시 환경 변수 설정 (`ENVIRONMENT=test`) 및 기본 설정값 오버라이드.
*   테스트용 암호화 키 및 기본 반환 URL 설정.
*   테스트 데이터 생성을 위한 Fixture 정의:
    *   `test_player`: 테스트용 플레이어 ID 생성.
    *   `test_partner`: 테스트용 파트너 데이터 생성 (DB 저장 포함).
    *   `test_wallet`: 테스트용 지갑 데이터 생성 (DB 저장 포함).
    *   `test_game`: 테스트용 게임 및 제공사 데이터 생성 (DB 저장 포함).
    *   `mock_db_session`, `mock_async_client`, `mock_redis_client` 등 외부 시스템 모킹 fixture.
    *   기타 DB 세션, API 클라이언트 등 테스트 실행에 필요한 환경 설정.

## API 라우터 테스트 (`tests/api/routers/`)

### `test_health.py`

*   **기본 상태 확인:** `/health` 엔드포인트 호출 시 정상 응답(200 OK) 반환 검증 (`test_basic_health_check`).
*   **상세 상태 확인:** `/health/detailed` 엔드포인트 호출 시 DB 연결 상태 등을 포함한 상세 정보 반환 검증 (`test_detailed_health_check`).

## 서비스 테스트 (`tests/services/`)

### `test_auth_service.py`

*   **파트너 인증:**
    *   유효한 자격 증명(파트너 코드, API 키) 제공 시 성공적으로 인증되고 토큰(액세스, 리프레시) 반환 검증 (`test_authenticate_partner_success`).
    *   (다른 테스트 케이스 포함 가능성: 잘못된 자격 증명, 비활성 파트너 등 실패 시나리오).
*   **API 키 검증:**
    *   유효한 API 키 검증 로직 테스트.
    *   만료/비활성/존재하지 않는 API 키 검증 테스트.
    *   잘못된 형식의 API 키 검증 테스트.
*   **IP 화이트리스트 검증:**
    *   파트너에게 화이트리스트 설정이 없을 경우 모든 IP 허용 검증 (`test_verify_ip_whitelist_no_list`).
    *   화이트리스트에 등록된 IP 주소/CIDR 범위에 대해 접근 허용 검증.
    *   화이트리스트에 없는 IP 주소에 대해 접근 거부(예외 발생) 검증.
*   **토큰 관리:**
    *   액세스 토큰 및 리프레시 토큰 생성 로직 검증.
    *   JWT 토큰 디코딩 및 유효성(만료, 서명 등) 검증.
    *   리프레시 토큰을 사용한 액세스 토큰 재발급 로직 검증.

### `test_game_service.py`

*   **게임 정보 관리:**
    *   ID로 특정 게임 정보 조회 검증 (`test_get_game`).
    *   활성 상태인 게임 목록 조회 검증 (페이지네이션 포함 가능성).
    *   제공사 ID별 게임 목록 조회 검증.
*   **게임 실행:**
    *   게임 실행 요청 시 유효한 실행 URL/토큰 생성 검증.
    *   플레이어 정보, 파트너 정보 등을 포함한 세션 생성 로직 검증.
*   **게임 세션 관리:**
    *   세션 ID로 게임 세션 조회/업데이트 기능 검증.
    *   세션 만료 처리 로직 검증.
*   **(추정)** 게임 라운드 처리 (베팅/승리 결과) 관련 로직 검증 (WalletService 연동 포함).

### `test_permission_check.py`

*   **권한 확인 로직 (`check_permission`):**
    *   API 키에 부여된 권한(단일, 특정, 와일드카드 등)을 기준으로 요청된 작업 수행 권한 유무 확인 검증.
    *   다양한 권한 저장 형식(리스트, JSON 문자열, 쉼표 구분 문자열 등) 지원 검증.
    *   필요한 권한이 없을 경우 `PermissionDeniedError` 예외 발생 검증.

### `test_wallet_service.py` (디렉토리: `tests/services/wallet/`)

*   **입금 (`credit`):**
    *   성공적인 입금 처리 및 잔액 증가 검증.
    *   유효하지 않은 요청(음수 금액, 필수 필드 누락 등) 거부 검증.
    *   존재하지 않는 플레이어/지갑 처리 검증.
    *   트랜잭션 중복 방지(멱등성 키 기반) 검증.
*   **출금 (`debit`):**
    *   성공적인 출금 처리 및 잔액 감소 검증.
    *   잔액 부족 시 출금 거부 검증.
    *   유효하지 않은 요청(음수 금액 등) 거부 검증.
    *   존재하지 않는 플레이어/지갑 처리 검증.
    *   트랜잭션 중복 방지(멱등성 키 기반) 검증.
*   **베팅 (`place_bet.py`):**
    *   성공적인 베팅 처리 및 잔액 차감 검증.
    *   잔액 부족 시 베팅 거부 검증.
    *   유효하지 않은 요청 검증.
    *   `GameSessionService` 연동 여부에 따른 베팅 처리 로직 검증 (`test_place_bet_without_game_session_service`).
*   **승리 기록 (`record_win.py`):**
    *   성공적인 승리 기록 및 잔액 증가 검증.
    *   유효하지 않은 요청(음수 금액 등) 거부 검증.
    *   `GameSessionService` 연동 여부에 따른 승리 기록 처리 로직 검증 (`test_record_win_without_game_session_service`).

### `test_wallet_boundary.py` (디렉토리: `tests/services/wallet/`) - 완료 (신규 추가)

*   **입금/출금/베팅/승리기록 경계값 검증:**
    *   **유효하지 않은 입력:** 음수 금액, 0 금액, 통화별 소수점 정밀도 위반, 통화 불일치 등의 경우 `InvalidAmountError` 또는 `CurrencyMismatchError` 발생 검증.
    *   **유효한 입력:** 최소 금액, 일반적인 큰 금액 등 유효한 경계값 입력 시 정상 처리(예외 미발생) 검증.
    *   **잔액 부족:** 출금/베팅 시 잔액과 정확히 같은 금액 또는 약간 더 큰 금액을 요청하는 경우 `InsufficientFundsError` 발생 또는 정상 처리(정확히 같은 금액) 검증.
    *   Mock 객체(`wallet_service`)를 사용하여 각 시나리오별 예상 예외 발생(`side_effect`) 및 정상 처리(`return_value`) 동작 확인.

## AML 테스트 (`tests/aml/`)

### `test_aml_service.py` (단위 테스트 중심)

*   **`analyze_transaction` 메서드 집중 테스트:**
    *   **고액 거래 탐지:** 설정된 통화별 임계값 초과 시 위험 점수 증가, 알림/보고 플래그 설정 검증 (`test_analyze_transaction_high_amount_deposit`). 임계값 미만 시 미탐지 검증 (`test_analyze_transaction_low_amount_deposit`).
    *   **행동 패턴 편차 탐지:** 과거 거래 내역과 비교하여 비정상적인 패턴 감지 로직 검증.
        *   **금액 편차:** 평균 대비 Z-score 기반으로 비정상적인 금액 탐지 검증 (`test_analyze_transaction_amount_pattern_deviation`).
        *   **시간 편차:** 평소 거래 없던 시간대 거래 발생 시 탐지 검증 (`test_analyze_transaction_time_pattern_deviation`).
        *   **빈도 편차:** 단기 거래 빈도 급증 시 탐지 검증. 임계값 경계 조건 검증 (`test_analyze_transaction_frequency_boundary`).
    *   **복합 편차 처리:** 여러 종류의 편차(시간+금액 등) 동시 발생 시 위험 점수 및 알림 수준 적절히 계산되는지 검증 (`test_analyze_transaction_multiple_deviations`).
    *   **(추정)** 자금 급속 이동(입금 후 즉시 출금) 패턴 탐지 검증 (`test_analyze_transaction_rapid_deposit_withdrawal`).
*   **내부 헬퍼 함수 모킹:** `_get_historical_transactions`, `_get_or_create_risk_profile`, `_create_alert` 등 내부 함수를 모킹하여 특정 로직 격리 및 검증.

### `test_aml_scenarios.py` (시나리오/통합 테스트 중심)

*   **WalletService - AMLService 연동 검증:**
    *   **단기간 내 대량 입출금 시나리오 (`test_large_rapid_transactions_detection`):** `WalletService`를 통해 고액 입금 후 즉시 출금 트랜잭션을 발생시키고, 이 과정에서 `AMLService.analyze_transaction`이 정상적으로 **호출되는지** (트리거되는지) 검증. (실제 분석 결과보다는 연동 자체에 초점).

## E2E 테스트 (`tests/e2e/`)

### `test_player_game_flow.py`

*   **(추정)** 실제 API 엔드포인트를 순차적으로 호출하여 사용자의 일반적인 플로우(예: 회원가입 -> 로그인 -> 입금 -> 게임 플레이(베팅/승리) -> 잔액 확인 -> 출금)가 시스템 전체적으로 정상 동작하는지 검증.
*   테스트 데이터 생성을 위한 유틸리티 함수 포함 (`generate_reference_id`).
