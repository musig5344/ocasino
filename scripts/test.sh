#!/bin/bash
set -e

# 가상 환경 활성화 (필요한 경우)
# source venv/bin/activate

# 환경 변수 로드
export $(grep -v '^#' .env | xargs)

# 단위 테스트 실행
echo "Running unit tests..."
python -m pytest tests/unit -v

# 통합 테스트 실행
echo "Running integration tests..."
python -m pytest tests/integration -v

# API 테스트 실행
echo "Running API tests..."
python -m pytest tests/api -v

# E2E 테스트 실행 (선택 사항)
if [ "$1" = "--e2e" ]; then
    echo "Running E2E tests..."
    python -m pytest tests/e2e -v
fi

echo "All tests completed!"