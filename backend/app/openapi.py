from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.openapi.docs import get_swagger_ui_html
from backend.core.config import settings

def custom_openapi(app: FastAPI):
    """Generate a custom OpenAPI schema."""
    if app.openapi_schema:
        return app.openapi_schema
    
    api_version = settings.VERSION if hasattr(settings, 'VERSION') else "1.0.0"
    project_name = settings.PROJECT_NAME if hasattr(settings, 'PROJECT_NAME') else "Casino Integration Platform API"
    
    openapi_schema = get_openapi(
        title=project_name,
        version=api_version,
        description="""
        # B2B 온라인 카지노 게임 통합 플랫폼 API
        
        이 API는 카지노 운영사, 게임 어그리게이터, 제휴사 등 다양한 비즈니스 파트너에게 
        게임 통합, 지갑 관리, 보고서 등의 서비스를 제공합니다.
        
        ## 인증
        
        모든 API 요청은 HTTP 헤더에 API 키를 포함해야 합니다:
        ```
        X-API-Key: your_api_key
        ```
        
        ## 보안
        
        - API 키는 파트너별로 발급되며, 권한 제어를 위해 사용됩니다.
        - 모든 API 엔드포인트는 HTTPS로 보호됩니다.
        - IP 화이트리스팅이 활성화된 경우, 허용된 IP에서만 API에 접근할 수 있습니다.
        
        ## 에러 처리
        
        모든 에러 응답은 다음 형식을 따릅니다:
        ```json
        {
            "error": {
                "code": "ERROR_CODE",
                "message": "Error description"
            }
        }
        ```
        
        주요 에러 코드:
        - `UNAUTHORIZED`: 인증 실패
        - `FORBIDDEN`: 권한 없음
        - `RESOURCE_NOT_FOUND`: 리소스 찾을 수 없음
        - `INVALID_REQUEST`: 잘못된 요청
        - `INSUFFICIENT_FUNDS`: 잔액 부족
        - `DUPLICATE_RESOURCE`: 중복 리소스
        - `SERVICE_UNAVAILABLE`: 서비스 이용 불가
        - `INTERNAL_ERROR`: 내부 서버 오류
        """,
        routes=app.routes,
    )
    
    # Add tags description
    openapi_schema["tags"] = [
        {"name": "Authentication", "description": "파트너 인증 및 API 키 관리"},
        {"name": "Partner Management", "description": "비즈니스 파트너 정보 및 설정 관리"},
        {"name": "Game Integration", "description": "게임 제공자 및 게임 통합 관리"},
        {"name": "Wallet", "description": "플레이어 지갑 및 금융 거래 관리"},
        {"name": "Reporting", "description": "보고서 및 정산 서비스"},
        {"name": "Health", "description": "API 상태 확인"}
    ]
    
    # Add security schemes
    if "components" not in openapi_schema:
        openapi_schema["components"] = {}
    openapi_schema["components"]["securitySchemes"] = {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "API Key for authentication"
        }
    }
    
    # Apply security globally or per-route as needed
    # Example: Apply ApiKeyAuth globally
    openapi_schema["security"] = [
        {"ApiKeyAuth": []}
    ]

    app.openapi_schema = openapi_schema
    return app.openapi_schema

def register_openapi(app: FastAPI):
    """Register custom OpenAPI schema and Swagger UI endpoint."""
    # Set the custom OpenAPI schema function
    app.openapi = lambda: custom_openapi(app)

    # Custom Swagger UI endpoint
    @app.get("/api/docs", include_in_schema=False)
    async def custom_swagger_ui_html_endpoint(): # Renamed to avoid conflict
        return get_swagger_ui_html(
            openapi_url=app.openapi_url, # Use app's openapi_url
            title=app.title + " - Swagger UI",
            swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js", # Updated version
            swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css", # Updated version
        ) 