# API 문서화 변경 로그

## [Unreleased] - 2024-07-30

### Added
- API 문서화 작업 시작.
- FastAPI 자동 생성 OpenAPI 스키마 (`/api/openapi.json`) 경로 확인.
- `redoc-cli` 설치 및 `openapi.json` 파일 추출 시도.
- `AuditLogMiddleware` 문제로 인한 OpenAPI 스키마 생성 오류 식별 및 임시 비활성화.
- 최종적으로 유효한 `openapi.json` 파일 생성 성공.
- `openapi.json` 기반 Redoc HTML 문서 (`api-docs-redoc.html`) 생성 성공.
- `docs/CHANGELOG.md` 파일 생성 및 기록 시작.

### Changed
- `backend/main.py`: `custom_openapi` 함수를 사용하여 스키마 커스터마이징 (태그, 보안 정의 등).
- `backend/core/config.py`: `AUTH_EXCLUDE_PATHS`에 `/api/openapi.json` 추가.

### Fixed
- (향후 수정 사항 기록)

### Removed
- (향후 제거 사항 기록) 