from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.core.config import settings
from backend.app.lifespan import lifespan # Import the lifespan context manager

def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    app = FastAPI(
        title=settings.PROJECT_NAME,
        description="Backend API for wallet and gaming services",
        version=settings.VERSION,
        docs_url=None,  # Disable default /docs, using custom one
        redoc_url=None, # Disable default /redoc
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        lifespan=lifespan, # Use the imported lifespan context manager
    )

    # Add CORS middleware
    if settings.BACKEND_CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        print("CORS middleware added with origins:", settings.BACKEND_CORS_ORIGINS)
    else:
        print("CORS middleware not added (no origins configured)")

    return app 