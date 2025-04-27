import uuid
import logging
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        # Log entry with request ID
        logger.info(f"Request started: {request.method} {request.url.path} (ID: {request_id})")
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            # Log exit with request ID and status code
            logger.info(f"Request finished: {request.method} {request.url.path} - {response.status_code} (ID: {request_id})")
            return response
        except Exception as e:
            logger.error(f"Request failed: {request.method} {request.url.path} (ID: {request_id}) - {e}", exc_info=True)
            # Ensure the header is added even if an exception occurs before the response object is created
            # Note: This might not be possible if the exception prevents response generation.
            # Consider adding a generic error response here or ensure exception handlers add the header.
            raise e # Re-raise the exception to be handled by exception handlers

def register_middlewares(app: FastAPI):
    """Register middlewares for the FastAPI app."""
    app.add_middleware(RequestIDMiddleware)
    # Add other middlewares here, e.g.:
    # from backend.middlewares.some_other_middleware import SomeOtherMiddleware
    # app.add_middleware(SomeOtherMiddleware) 