import os
from dotenv import load_dotenv

# .env 파일 로드 (프로젝트 루트에 .env 파일이 있다고 가정)
# env.py 파일의 위치를 기준으로 .env 파일 경로를 설정합니다.
# 일반적으로 env.py는 migrations 디렉토리 안에 있으므로, 상위 디렉토리의 .env를 찾습니다.
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env') # env.py 기준 상위 폴더의 .env
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path)
else:
    # 또는 루트에 바로 .env가 있다면
    dotenv_path_root = os.path.join(os.path.dirname(__file__), '..', '..', '.env') # env.py 기준 상위-상위 폴더의 .env (조정 필요할 수 있음)
    if os.path.exists(dotenv_path_root):
        load_dotenv(dotenv_path=dotenv_path_root)
    else:
        # .env 파일 못 찾을 경우 경고 또는 기본값 처리
        print(f"Warning: .env file not found at {dotenv_path} or {dotenv_path_root}")
        # 필요한 경우 여기서 기본 DATABASE_URL 설정 또는 오류 발생

from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine
import asyncio

from alembic import context

# 프로젝트의 Base 모델 임포트
import sys
from pathlib import Path
# 프로젝트 루트 디렉토리를 sys.path에 추가 (env.py가 루트에서 실행될 때 기준)
root_dir = Path(__file__).parent.parent # env.py의 위치에서 루트까지의 경로 조정 - 수정: .parent 하나 제거
sys.path.insert(0, str(root_dir))
from backend.db.database import Base

# 모든 SQLAlchemy 모델 임포트 (Alembic이 인식하도록)
from backend.models.domain import partner, wallet, game, api_key # transaction 제거

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = Base.metadata # Base.metadata로 설정

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    # 환경 변수에서 데이터베이스 URL 가져오기
    db_url = os.getenv('DATABASE_URL')
    if db_url is None:
        raise ValueError("DATABASE_URL environment variable is not set")
    
    # connectable = create_async_engine(
    #     config.get_main_option("sqlalchemy.url"), # 이전 방식 주석 처리
    #     poolclass=pool.NullPool,
    # )
    connectable = create_async_engine(db_url, poolclass=pool.NullPool)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def do_run_migrations(connection):
    """실제 마이그레이션을 수행하는 동기 함수 (run_sync 내부에서 실행됨)"""
    context.configure(
        connection=connection, target_metadata=target_metadata
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
