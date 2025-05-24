import os
import base64

from http import HTTPStatus
from functools import wraps
from flask_restx import abort
from werkzeug.exceptions import BadRequest
from flask import request

from logger import logging

logger = logging.getLogger(__file__)

def handle_request_exception(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except BadRequest as bad_request:
            # 改用 str(bad_request)，避免 .data 屬性不存在
            error_message = str(bad_request)
            logger.error("Bad Request: %s", error_message)
            return abort(
                HTTPStatus.BAD_REQUEST,
                message="Bad Request",
                error=error_message,
                status=1,
                result=None,
            )
        except Exception as e:
            error_message = f"{e.__class__.__name__}: {e}"
            logger.error("An error occurred: %s", error_message)
            return abort(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                message="Internal Server Error",
                error=error_message,
                status=1,
                result=None,
            )

    return wrapper

def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        expected_token = f"Bearer {os.environ.get('API_SECRET_KEY')}"

        if auth_header != expected_token:
            return {"error": "Unauthorized"}
        return f(*args, **kwargs)
    return decorated_function

def encode_photo_to_base64(path: str) -> str | None:
    """圖片路徑轉 base64 字串，若不存在回傳 None"""
    if not path or not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")