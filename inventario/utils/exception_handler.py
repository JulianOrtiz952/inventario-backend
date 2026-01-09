from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
import logging

logger = logging.getLogger(__name__)

def custom_exception_handler(exc, context):
    """
    Custom exception handler that ensures all errors are returned as JSON,
    even 500 errors that normally produce HTML in Django DEBUG mode.
    """
    # Call REST framework's default exception handler first,
    # to get the standard error response.
    response = exception_handler(exc, context)

    # If response is None, it means it's an exception not handled by DRF
    # (e.g. system errors, 500s, standard Python exceptions).
    if response is None:
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        
        # Return a generic JSON 500 error
        return Response(
            {
                "detail": "Error interno del servidor.",
                "error_type": type(exc).__name__,
                "debug_message": str(exc) 
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    # If response is not None, it's a DRF-handled exception (Validation, Auth, etc.)
    # We can standardize the format here if needed, but usually DRF format is fine.
    # Just ensuring it's JSON is the key.
    
    return response
