import base64
import os

from flask_restx import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, ConstructionSite, User
from payload import (
    api_ns, general_output_payload, site_input_payload, site_output_payload, site_list_output
)
from werkzeug.exceptions import BadRequest
from util import handle_request_exception
from payload import api
from logger import logging

logger = logging.getLogger(__file__)
PHOTO_DIR = "static/site_photos"
os.makedirs(PHOTO_DIR, exist_ok=True)


def save_photo(site_id: str, b64: str) -> str:
    """Base64 轉檔並回傳路徑"""
    file_path = os.path.join(PHOTO_DIR, f"{site_id}.jpg")
    with open(file_path, "wb") as f:
        f.write(base64.b64decode(b64))
    return file_path

def save_photos(site_id: str, photo_list: list[str]) -> list[str]:
    """儲存多張 Base64 圖片，回傳每張路徑"""
    saved_paths = []
    for idx, b64 in enumerate(photo_list):
        filename = f"{site_id}_{idx}.jpg"
        file_path = os.path.join(PHOTO_DIR, filename)
        with open(file_path, "wb") as f:
            f.write(base64.b64decode(b64))
        saved_paths.append(file_path)
    return saved_paths

# ------------------  工地總覽  ------------------

@api_ns.route("/api/sites")
class SiteCollection(Resource):
    """GET 列表 │ POST 建立 (任何權限)"""

    @handle_request_exception
    @jwt_required()
    @api.marshal_with(site_list_output)
    def get(self):
        try:
            sites = ConstructionSite.query.all()
            return {"status": 0, "result": [site.to_dict() for site in sites]}
        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0]
            logger.warning(f"login Error: [{error_class}] detail: {detail}")
            return {'status':1, 'result': str(e)}

    @handle_request_exception
    @jwt_required()
    @api.expect(site_input_payload)
    @api.marshal_with(general_output_payload)
    def post(self):
        user = User.query.get(get_jwt_identity())
        if user is None:
            return {"status": 1, "result": f"{get_jwt_identity()} 使用者不存在"}, 403

        data = api.payload
        coordinates = data.get("coordinates")
        latitude = longitude = None

        if coordinates:
            try:
                lat_str, lon_str = coordinates.split(",")
                latitude = float(lat_str.strip())
                longitude = float(lon_str.strip())
            except ValueError:
                raise BadRequest("經緯度輸入錯誤. 期望 'lat,lon'")

        photo = None

        site = ConstructionSite(
            vendor=data["vendor"],
            location=data["location"],
            latitude=latitude,
            longitude=longitude,
            photo=photo,
            created_by=user.id,
        )
        if b64 := data.get("photo"):
            photo = save_photo(site.id, b64)

        db.session.add(site)
        db.session.commit()
        return {"status": 0, "result": "工地建立成功"}



@api_ns.route("/api/sites/<string:site_id>")
class SiteItem(Resource):
    """GET 單筆 │ PUT 編輯 (任何) │ DELETE 刪除 (限權限2)"""
    @handle_request_exception
    @jwt_required()
    @api.marshal_with(site_output_payload)
    def get(self, site_id):
        site = ConstructionSite.query.get_or_404(site_id)
        return {"status": 0, "result": site}


    @handle_request_exception
    @jwt_required()
    @api.expect(site_input_payload)
    @api.marshal_with(general_output_payload)
    def put(self, site_id):
        try:
            data = api.payload
            site = ConstructionSite.query.get_or_404(site_id)
            coordinates = data.get("coordinates")
            latitude = longitude = None

            if coordinates:
                try:
                    lat_str, lon_str = coordinates.split(",")
                    latitude = float(lat_str.strip())
                    longitude = float(lon_str.strip())
                    site.latitude = latitude
                    site.longitude = longitude
                except ValueError:
                    raise BadRequest("經緯度輸入錯誤. 期望 'lat,lon'")
                print(f"latitude: {latitude}, longitude: {longitude}")
            else:
                site.latitude  = data.get("latitude",  site.latitude)
                site.longitude = data.get("longitude", site.longitude)
                

            site.vendor   = data.get("vendor",   site.vendor)
            site.location = data.get("location", site.location)
            site.photo    = data.get("photo",    site.photo)


            if b64 := data.get("photo"):
                site.photo = save_photo(site.id, b64)

            db.session.commit()
            return {"status": 0, "result": "工地更新成功"}
        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0]
            logger.warning(f"login Error: [{error_class}] detail: {detail}")
            return {'status':1, 'result': str(e)}

    @handle_request_exception
    @jwt_required()
    @api.marshal_with(general_output_payload)
    def delete(self, site_id):
        user = User.query.get(get_jwt_identity())
        if user== None:
            return {"status": 1, "result": "使用者不存在"}, 403
        if user.permission < 2:
            return {"status": 1, "result": "僅限最高權限可移除工地"}, 403

        site = ConstructionSite.query.get_or_404(site_id)
        db.session.delete(site)
        db.session.commit()
        return {"status": 0, "result": "工地已刪除"}

    
