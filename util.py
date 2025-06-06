import os
import time
import functools
import json
import base64

from http import HTTPStatus
from functools import wraps
from flask_restx import abort
from werkzeug.exceptions import BadRequest
from flask import make_response, Response

from logger import logging

logger = logging.getLogger(__file__)

def handle_request_exception(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except BadRequest as bad_request:
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

def encode_photo_to_base64(path: str) -> str | None:
    """圖片路徑轉 base64 字串，若不存在回傳 None"""
    if not path or not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def photo_path_to_base64(photo_field: str | list[str]) -> list[str]:
    """
    將圖片路徑字串或列表轉換為 base64 字串列表。
    
    Args:
        photo_field (str | list[str]): 可能為 JSON 字串或圖片路徑列表

    Returns:
        list[str]: 對應的 base64 圖片字串列表
    """
    try:
        photo_list = json.loads(photo_field) if isinstance(photo_field, str) else (photo_field or [])
        return [encode_photo_to_base64(path) for path in photo_list]
    except Exception as e:
        raise BadRequest(f"圖片轉換 base64 失敗：{e}")

def save_photos(name:str, photo_list: list[str], PHOTO_DIR) -> list[str]:
    """儲存多張 Base64 圖片，回傳每張路徑"""
    os.makedirs(PHOTO_DIR, exist_ok=True)
    logger.debug(f"Saving {photo_list} photos for {name}")
    photos_path = []
    for idx, b64 in enumerate(photo_list):
        try:
            b64 = b64.strip()
            if "," in b64:
                b64 = b64.split(",", 1)[-1]
        except Exception as e:
            raise BadRequest(f"第 {idx+1} 張圖片 base64 格式錯誤：{e}")
        filename = f"{name}_{idx}.jpg"
        file_path = os.path.join(PHOTO_DIR, filename)
        with open(file_path, "wb") as f:
            f.write(base64.b64decode(b64))
        photos_path.append(file_path)
    return photos_path

def delete_photo_file(photo_field: str | list[str], PHOTO_DIR: str) -> None:
    """
    根據 JSON 字串或路徑列表，刪除指定目錄中的圖片檔案。

    Args:
        photo_field (str | list[str]): 可能為 JSON 字串或圖片檔名列表
        PHOTO_DIR (str): 圖片所在的資料夾路徑

    Raises:
        BadRequest: 若刪除過程中出現錯誤
    """
    try:
        photo_list = json.loads(photo_field) if isinstance(photo_field, str) else (photo_field or [])
        for path in photo_list:
            full_path = os.path.join(PHOTO_DIR, path)
            if os.path.exists(full_path):
                os.remove(full_path)
    except Exception as e:
        raise BadRequest(f"圖片刪除失敗：{e}")


def measure_db_time(func):
    """
    裝飾任何 Flask-View；量測函式執行時間並
    1. 以 logger.info() 紀錄
    2. 於回應加上 X-DB-Runtime header
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = round(time.perf_counter() - start, 6)  # 秒，保留 6 位
        logger.info("%s 花了 %.6f s (DB round-trip)", func.__name__, elapsed)

        # -------- 將秒數塞進 HTTP Header --------
        # ─ Flask-RESTx 允許直接回傳 dict / tuple / Response
        if isinstance(result, Response):
            result.headers["X-DB-Runtime"] = str(elapsed)
            return result

        if isinstance(result, tuple):
            # (payload, status), (payload, status, headers) 都支援
            payload, *rest = result
            response = make_response(payload, *rest)
        else:
            # 純 dict 情況
            response = make_response(result)

        response.headers["X-DB-Runtime"] = str(elapsed)
        return response

    return wrapper