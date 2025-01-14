from functools import wraps
from flask_restx import abort
from http import HTTPStatus
from werkzeug.exceptions import BadRequest
from logger import logging

logger = logging.getLogger(__file__)

def handle_request_exception(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except BadRequest as bad_request:
            logger.error("Bad Request: %s", bad_request.data)
            return abort(
                HTTPStatus.BAD_REQUEST,
                "",
                error=bad_request.data,
                status=1,
                result=None,
            )
        except Exception as e:
            error_message = f"{e.__class__.__name__}: {e}"
            logger.error("An error occurred: %s", error_message)
            return abort(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "",
                error=error_message,
                status=1,
                result=None,
            )

    return wrapper
