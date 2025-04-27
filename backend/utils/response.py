from typing import List, Optional, Any, TypeVar, Generic
from math import ceil

from backend.core.schemas import StandardResponse, PaginatedData, PaginatedResponse

T = TypeVar('T')

def success_response(data: Optional[T] = None, message: str = "Success") -> StandardResponse[T]:
    """Creates a standard successful response.

    Args:
        data: The main data payload (optional).
        message: A descriptive message (optional).

    Returns:
        A StandardResponse object.
    """
    return StandardResponse[T](success=True, message=message, data=data)

def paginated_response(
    items: List[T], 
    total: int, 
    page: int, 
    page_size: int, 
    message: str = "Success"
) -> PaginatedResponse[T]:
    """Creates a standard paginated response.

    Args:
        items: The list of items for the current page.
        total: The total number of items across all pages.
        page: The current page number (1-based).
        page_size: The number of items per page.
        message: A descriptive message (optional).
        
    Returns:
        A PaginatedResponse object.
    """
    if page_size <= 0:
        total_pages = 1 if total > 0 else 0
    else:
        total_pages = ceil(total / page_size)
        
    paginated_data = PaginatedData[T](
        items=items,
        page=page,
        page_size=page_size,
        total_items=total,
        total_pages=total_pages
    )
    return PaginatedResponse[T](success=True, message=message, data=paginated_data)

# Note: While the utility functions are convenient, you can also directly
# instantiate the StandardResponse or PaginatedResponse models in your endpoints.
# Example:
# return StandardResponse[MySchema](data=my_data_instance)
# return PaginatedResponse[MySchema](data=PaginatedData(...)) 