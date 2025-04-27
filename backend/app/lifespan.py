import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from backend.db.database import read_engine, write_engine

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager."""
    logger.info("Lifespan: Startup")
    # Perform startup activities here, e.g., DB connection pool, cache init
    yield
    # Perform shutdown activities here, e.g., close DB connections
    logger.info("Lifespan: Shutdown")
    try:
        if read_engine:
            await read_engine.dispose()
        if write_engine:
            await write_engine.dispose()
        logger.info("Database connections closed successfully.")
    except Exception as e:
        logger.error(f"Error closing database connections: {e}", exc_info=True) 