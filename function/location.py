import os
import base64
import json



from flask_restx import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from static.models import db, ConstructionSite, User
from static.payload import (
    api_ns, general_output_payload, site_input_payload, site_output_payload, site_list_output
)
from werkzeug.exceptions import BadRequest
from static.util import *
from static.payload import api
from static.logger import logging

logger = logging.getLogger(__file__)
PHOTO_DIR = "static/site_photos"




# ------------------  工地總覽  ------------------

@api_ns.route("/api/sites")
class SiteCollection(Resource):
    """GET 列表 │ POST 建立 (任何權限)"""
    @measure_db_time
    @handle_request_exception
    @jwt_required()
    @api.marshal_with(site_list_output)
    def get(self):
        try:
            sites = ConstructionSite.query.filter_by(is_deleted=False).all()
            return {"status": 0, "result": [site.to_dict(include_photo=False) for site in sites]}
        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0]
            logger.warning(f"login Error: [{error_class}] detail: {detail}")
            return {'status':1, 'result': str(e)}

    @jwt_required()
    @handle_request_exception
    @api.expect(site_input_payload)
    @api.marshal_with(general_output_payload)
    def post(self):
        user = User.query.get(get_jwt_identity())
        if user is None:
            return {"status": 1, "result": "使用者不存在"}, 403

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



        site = ConstructionSite(
            vendor = data["vendor"],
            location = data["location"],
            latitude = latitude,
            longitude = longitude,
            note = data.get("note"),
            created_by = user.id
        )
        db.session.add(site)
        db.session.flush()  # 先儲存以獲得 site.id

        if photo_list := data.get("photo"): 
            site_id_prefix = site.id[:8]
            filename = f"{site_id_prefix}_{site.vendor}"
            photos_path = save_photos(filename, photo_list, PHOTO_DIR)
            site.photo = json.dumps(photos_path)

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
        result = site.to_dict(include_photo=True)
        return {"status": 0, "result": result}


    @handle_request_exception
    @jwt_required()
    @api.expect(site_input_payload)
    @api.marshal_with(general_output_payload)
    def put(self, site_id):
        try:
            data = api.payload
            site = ConstructionSite.query.get_or_404(site_id)

            # 經緯度處理
            coordinates = data.get("coordinates")
            if coordinates:
                try:
                    lat_str, lon_str = coordinates.split(",")
                    site.latitude = float(lat_str.strip())
                    site.longitude = float(lon_str.strip())
                except ValueError:
                    raise BadRequest("經緯度輸入錯誤. 期望 'lat,lon'", 400)
            else:
                site.latitude = data.get("latitude", site.latitude)
                site.longitude = data.get("longitude", site.longitude)

            # 更新 vendor / location
            site.vendor = data.get("vendor", site.vendor)
            site.location = data.get("location", site.location)
            site.note = data.get("note", site.note)

            # 儲存圖片（如有）
            if photo_list := data.get("photo"):
                site_id_prefix = site.id[:8]
                filename = f"{site_id_prefix}_{site.vendor}"
                photos_path = save_photos(filename, photo_list, PHOTO_DIR)
                site.photo = json.dumps(photos_path)

            db.session.commit()
            return {"status": 0, "result": "工地更新成功"}

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0] if e.args else ""
            logger.warning(f"PUT 工地更新失敗: [{error_class}] detail: {detail}")
            return {"status": 1, "result": str(e), "error": detail}


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
        site.is_deleted = True
        db.session.commit()
        return {"status": 0, "result": "工地已刪除"}

    
