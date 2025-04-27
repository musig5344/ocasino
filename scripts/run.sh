#!/bin/bash
set -e

# 가상 환경 활성화 (필요한 경우)
# source venv/bin/activate

# 환경 변수 로드
export $(grep -v '^#' .env | xargs)

# 마이그레이션 실행
echo "Running database migrations..."
alembic upgrade head

# 개발 서버 실행
echo "Starting development server..."
uvicorn backend.main:app --reload --host 0.0.0.0 --port $PORT