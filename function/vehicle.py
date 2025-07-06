import re
from datetime import datetime, date, timedelta
import json
import pytz

from flask_restx import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import joinedload
from static.models import db, Crane, User, CraneUsage, CraneNotice, CraneMaintenance, ConstructionSite, NoticeColor

from static.payload import (
    api_ns, api, api_crane, api_test, api_notice,
    add_crane_payload, general_output_payload,
    add_usage_payload, add_notice_payload, add_maintenance_payload,
    notice_color_model
)
from static.util import (
    handle_request_exception, save_photos, 
    photo_path_to_base64, delete_photo_file

)
from static.logger import logging

logger = logging.getLogger(__file__)

tz = pytz.timezone('Asia/Taipei')
PHOTO_DIR = "static/crane_photos"
NOTICE_DIR = "static/crane_notices"
MAINTANCE_DIR = "static/crane_maintenances"

@api_crane.route("/api/show_cranes", methods=["GET"])
class ShowCranes(Resource):
    @jwt_required()
    @handle_request_exception
    def get(self):
        """
        取得所有吊車的基本資訊
        """
        try:
            rows = db.session.scalars(
                db.select(Crane.crane_number).order_by(Crane.crane_number)
            ).all()
            result = [{"crane_number": cn} for cn in rows]
            return {"status": "0", "result": result}, 200
        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0] if e.args else str(e)
            logger.exception(f"Show Cranes Error: [{error_class}] {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400

@api_crane.route('/api/cranes', methods=['GET', 'POST'])
class Create_crane(Resource):
    @jwt_required()
    @handle_request_exception
    def get(self):
        try:
            cranes = (Crane.query.options(joinedload(Crane.site)).all())
            result = []
            for crane in cranes:
                # 計算累計時數
                usages = CraneUsage.query.filter_by(crane_id=crane.id).all()
                total_usage = crane.initial_hours + sum(u.daily_hours for u in usages)

                # 判斷是否超過臨界值
                threshold = 450 if crane.crane_type == "履帶" else 950

                result.append({
                    "id": crane.id,
                    "crane_number": crane.crane_number,
                    "crane_type": crane.crane_type,
                    "site": {
                        "id": crane.site.id,
                        "vendor": crane.site.vendor,
                        "location": crane.site.location,
                        "latitude": crane.site.latitude,
                        "longitude": crane.site.longitude
                        }if crane.site else None,
                    "latitude": crane.latitude,
                    "longitude": crane.longitude,
                    "total_usage_hours": total_usage,
                    "alert": total_usage > threshold  
                })
            return {"status": "0", "result": result}, 200
        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0] if e.args else str(e)
            logger.exception(f"Add Crane Error: [{type(e).__name__}] {detail}")
            logger.warning(f"Get Crane Error: [{error_class}] detail: {detail}")
            return {'status': 1, 'result': error_class, "error": e.args}, 400
        
    @api.expect(add_crane_payload)
    @api.marshal_with(general_output_payload)
    @jwt_required()
    def post(self):
        try:
            data = api.payload
            crane_number = data.get('crane_number')
            crane_type = data.get('crane_type')
            initial_hours = data.get('initial_hours', 100)
            site_id = data.get("site_id")

            if not (crane_number and site_id):
                return {"status": 1, "result": "缺少車號或是工地ID"}, 400
            
            user = User.query.get(get_jwt_identity())
            if not user or user.permission < 1:
                return {"status": 1, "result": "使用者不存在" if not user else "使用者權限不足"}, 403


            # ---------- 1. 同車號不能重覆 ----------
            if Crane.query.filter_by(crane_number=crane_number).first():
                return {"status": 1, "result": "吊車車號已存在"}, 409
            
            # -------- 2. 查工地 --------
            site = ConstructionSite.query.get(site_id)
            if not site:
                return {"status": 1, "result": "找不到工地"}, 404

            new_crane = Crane(
                crane_number=crane_number,
                crane_type=crane_type,
                initial_hours=initial_hours,
                site=site,
                latitude=site.latitude,
                longitude=site.longitude,
            )
            db.session.add(new_crane)
            db.session.flush() 

            usage = CraneUsage(
                crane_id=new_crane.id,
                usage_date=date.today(),
                daily_hours=8,
            )
            db.session.add(usage)


            if photo_list := data.get("photo"): 
                photos_path = save_photos(crane_number, photo_list, PHOTO_DIR)
                new_crane.photo = json.dumps(photos_path)
            db.session.commit()
            
            return {"status": '0', "result": "拖車成功創建"}, 200
        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0] if e.args else str(e)
            logger.warning(f"Add Crane Error: [{error_class}] detail: {detail}")
            return {'status': 1, 'result': error_class, "error": e.args}, 400
          
@api_crane.route('/api/cranes/<int:crane_id>', methods=['GET', 'PUT', 'DELETE'])
class Crane_detail(Resource):
    @jwt_required()
    @handle_request_exception
    def get(self, crane_id):
        try:
            crane = Crane.query.get(crane_id)
            if crane is None:
                return {"status": "1", "result": "找不到指定的吊車"}, 404
            
            usages = CraneUsage.query.filter_by(crane_id=crane_id).all()
            total_usage = crane.initial_hours + sum(u.daily_hours for u in usages)
            threshold = 500 if crane.crane_type == "履帶" else 1000
            alert = total_usage > threshold

            base64_photos = photo_path_to_base64(crane.site.photo)

            data = {
                "id": crane.id,
                "crane_number": crane.crane_number,
                "crane_type": crane.crane_type,
                "site": {
                        "id": crane.site.id,
                        "vendor": crane.site.vendor,
                        "location": crane.site.location,
                        "latitude": crane.site.latitude,
                        "longitude": crane.site.longitude,
                        "photo": base64_photos
                        }if crane.site else None,
                "total_usage_hours": total_usage,
                "alert": alert
            }
            return {"status": '0', "result": data}, 200
        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0] if e.args else str(e)
            logger.warning(f"Get Crane Detail Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400
        
    @jwt_required()
    @handle_request_exception
    @api.expect(add_crane_payload)
    @api.marshal_with(general_output_payload)
    def put(self, crane_id):
        try:
            crane = Crane.query.get(crane_id)

            if crane is None:
                return {"status": "1", "result": "找不到指定的吊車"}, 404
            
            data = api.payload
            new_crane_number = data.get('crane_number')
            new_site_id = data.get("site_id")

             # ---------- 1. 驗證使用者 ----------
            # user = User.query.get(get_jwt_identity())
            # if not user or user.permission < 1:
            #     return {
            #         "status": 1, "result": "使用者不存在" if not user else "使用者權限不足"
            #     }, 403
            # ---------- 1. 驗證 crane_number 是否重複 ----------
            if new_crane_number and new_crane_number != crane.crane_number:
                if Crane.query.filter_by(crane_number=new_crane_number).first():
                    return {"status": 1, "result": "吊車車號已存在"}, 409
                crane.crane_number = new_crane_number

             # ---------- 2. 更新基本欄位 ----------
            crane.crane_type = data.get('crane_type', crane.crane_type)
            crane.initial_hours = data.get('initial_hours', crane.initial_hours)

            # ---------- 3. 更新工地資訊與位置 ----------
            if new_site_id:
                site = ConstructionSite.query.get(new_site_id)
                if not site:
                    return {"status": 1, "result": "找不到工地"}, 404
                crane.site = site
            crane.latitude = data.get("latitude", crane.latitude)
            crane.longitude = data.get("longitude", crane.longitude)

            # ---------- 4. 更新圖片 ----------
            if photo_list := data.get("photo"):
                photos_path = save_photos(crane.crane_number, photo_list, PHOTO_DIR)
                crane.photo = json.dumps(photos_path)



            db.session.commit()
            return {"status": '0', "result": "拖車已成功更新."}, 200
        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args if e.args else (str(e),)
            logger.warning(f"Get Crane Detail Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400

        
# ------------------------------
#  Usage (CraneUsage) 相關 API
# ------------------------------
@api_test.route('/api/cranes/<int:crane_id>/usages', methods=['GET', 'POST'])
class Create_usage(Resource):
    """
    GET: 取得某台吊車所有的使用紀錄 (CraneUsage)
    POST: 新增當日使用紀錄
    """

    @handle_request_exception
    @jwt_required()
    def get(self, crane_id):
        """
        取得指定 crane_id 的所有使用紀錄
        """
        try:

            crane = Crane.query.get(crane_id)
            if crane is None:
                return {"status": "1", "result": "找不到指定吊車"}, 404
            
            usages = CraneUsage.query.filter(
                CraneUsage.crane_id == crane_id,
            ).order_by(CraneUsage.usage_date.desc()).all()
            result = []
            for u in usages:
                result.append({
                    "id": u.id,
                    "usage_date": u.usage_date.isoformat(),
                    "daily_hours": u.daily_hours,
                })
            return {"status": "0", "result": result}, 200

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0] if e.args else str(e)
            logger.warning(f"Get Usage Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400

    @handle_request_exception
    @jwt_required()
    @api_ns.expect(add_usage_payload)                 # 如果有定義 usage payload
    @api_ns.marshal_with(general_output_payload)      # 和您原本的回傳格式一致
    def post(self, crane_id):
        """
        新增使用紀錄
        """
        try:
            data = api_ns.payload
            usage_date = data.get('usage_date')
            daily_hours = data.get('daily_hours', 8)

            # 如要檢查使用者權限
            user = User.query.get(get_jwt_identity())
            if user is None:
                return {"status": "1", "result": "使用者不存在"}, 403
            if user.permission < 0:
                return {"status": "1", "result": "使用者權限不足"}

            # 判斷日期格式或預設值
            if not usage_date:
                usage_date = datetime.now(tz).date()
            else:
                usage_date = datetime.strptime(usage_date, "%Y-%m-%d").date()

            new_usage = CraneUsage(
                crane_id=crane_id,
                usage_date=usage_date,
                daily_hours=daily_hours
            )

            db.session.add(new_usage)
            db.session.commit()
            return {"status": "0", "result": "Usage record created."}, 201

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0] if e.args else str(e)
            logger.warning(f"Add Usage Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400


@api_test.route('/api/usages/<int:usage_id>', methods=['GET', 'PUT', 'DELETE'])
class Usage(Resource):
    """
    針對單筆 CraneUsage 記錄的 查詢 / 更新 / 刪除
    """

    @handle_request_exception
    @jwt_required()
    def get(self, usage_id):
        """
        取得單筆 usage 資訊
        """
        try:
            usage = CraneUsage.query.get(usage_id)
            if usage is None:
                return {"status": "1", "result": "找不到指定的使用紀錄"}, 404
            
            data = {
                "id": usage.id,
                "crane_id": usage.crane_id,
                "usage_date": usage.usage_date.isoformat(),
                "daily_hours": usage.daily_hours
            }
            return {"status": "0", "result": data}, 200

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0] if e.args else str(e)
            logger.warning(f"Get Usage Detail Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400

    @handle_request_exception
    @jwt_required()
    @api_ns.expect(add_usage_payload)
    @api_ns.marshal_with(general_output_payload)
    def put(self, usage_id):
        """
        更新單筆使用紀錄
        """
        try:
            usage = CraneUsage.query.get_or_404(usage_id)
            data = api_ns.payload
            if 'usage_date' in data and data['usage_date']:
                usage.usage_date = datetime.strptime(data['usage_date'], "%Y-%m-%d").date()
            if 'daily_hours' in data:
                usage.daily_hours = data['daily_hours']

            db.session.commit()
            return {"status": "0", "result": "Usage record updated."}, 200

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0] if e.args else str(e)
            logger.warning(f"Update Usage Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400

    @handle_request_exception
    @jwt_required()
    def delete(self, usage_id):
        """
        刪除單筆使用紀錄
        """
        try:
            usage = CraneUsage.query.get(usage_id)
            if usage is None:
                return {"status": "1", "result": "找不到指定的使用紀錄"}, 404
            db.session.delete(usage)
            db.session.commit()
            return {"status": "0", "result": "Usage record deleted."}, 200

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0] if e.args else str(e)
            logger.warning(f"Delete Usage Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400


# ------------------------------
#  Notice (CraneNotice) 相關 API
# ------------------------------
@api_notice.route('/api/cranes/<int:crane_id>/notices', methods=['GET', 'POST'])
class Create_notice(Resource):
    """
    GET: 取得某台吊車的所有注意事項
    POST: 為某台吊車新增注意事項
    """

    @jwt_required()
    @handle_request_exception
    def get(self, crane_id):
        """
        查詢 notice 列表
        """
        try:
            if not Crane.query.get(crane_id):
                return {"status": "1", "result": f"找不到 ID 為 {crane_id} 的吊車"}, 404
            
            # cutoff_date = datetime.now(tz).date() - timedelta(days=30)
            # print(cutoff_date)
            
            notices = (
                CraneNotice.query
                .filter_by(crane_id=crane_id)
                # .filter(CraneNotice.notice_date >= cutoff_date)
                .order_by(CraneNotice.notice_date.desc())
                .all()
            )
            
            
            result = list()
            for n in notices:
                raw = n.photo or []                     # None → []
                photo_list = json.loads(raw) if isinstance(raw, str) else raw
                has_photo = bool(photo_list)  
                result.append({
                    "id": n.id,
                    "notice_date": n.notice_date.isoformat(),
                    "status": n.status,
                    "title": n.title,
                    "description": n.description,
                    "has_photo": has_photo
                })
            return {"status": "0", "result": result}, 200

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0] if e.args else str(e)
            logger.warning(f"Get Notices Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400

    @handle_request_exception
    @jwt_required()
    @api_ns.expect(add_notice_payload)
    @api_ns.marshal_with(general_output_payload)
    def post(self, crane_id):
        """
        新增注意事項
        """
        try:
            user = User.query.get(get_jwt_identity())
            if user.permission < 0:
                return {"status": "1", "result": "使用者權限不足"}

            data = api_ns.payload
            notice_date = data.get('notice_date')
            status = data.get('status')
            title = data.get('title')
            description = data.get('description')

            if not notice_date:
                notice_date = datetime.now(tz).date()
            else:
                notice_date = datetime.strptime(notice_date, "%Y-%m-%d").date()

            new_notice = CraneNotice(
                crane_id=crane_id,
                notice_date=notice_date,
                status=status,
                title=title,
                description=description,
                created_by=user.id,
                updated_by=user.id
            )
            db.session.add(new_notice)
            db.session.commit()

            if photo_list := data.get("photo"):
                filename = f"{crane_id}_{notice_date.strftime('%Y%m%d')}"
                photos_path = save_photos(filename, photo_list, NOTICE_DIR)
                new_notice.photo = json.dumps(photos_path)

            db.session.commit()
            return {"status": "0", "result": "吊車注意事項已成功創建."}, 200

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0] if e.args else str(e)
            logger.warning(f"Add Notice Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400


@api_notice.route('/api/notices/<int:notice_id>', methods=['GET', 'PUT', 'DELETE'])
class Notice(Resource):
    """
    針對單筆 Notice 的 查詢 / 更新 / 刪除
    """
    @jwt_required()
    @handle_request_exception
    def get(self, notice_id):
        """
        取得單筆 Notice 資訊
        """
        try:
            notice = CraneNotice.query.get(notice_id)
            if notice is None:
                return {"status": "1", "result": "找不到指定的注意事項"}, 404
            
            base64_photos = photo_path_to_base64(notice.photo)
            data = {
                "id": notice.id,
                "crane_id": notice.crane_id,
                "notice_date": notice.notice_date.isoformat(),
                "status": notice.status,
                "title": notice.title,
                "description": notice.description,
                "photo": base64_photos
            }
            return {"status": "0", "result": data}, 200

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0] if e.args else str(e)
            logger.warning(f"Get Notice Detail Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400
        
    @jwt_required()
    @handle_request_exception
    @api_ns.expect(add_notice_payload)
    @api_ns.marshal_with(general_output_payload)
    def put(self, notice_id):
        """
        更新單筆 Notice
        """
        try:
            notice = CraneNotice.query.get(notice_id)
            if notice is None:
                return {"status": "1", "result": "找不到指定的注意事項"}, 404
            user = User.query.get(get_jwt_identity())
            notice.updated_by = user.id
            data = api_ns.payload

            if 'notice_date' in data and data['notice_date']:
                notice.notice_date = datetime.strptime(data['notice_date'], "%Y-%m-%d").date()
            if 'status' in data:
                notice.status = data['status']
            if 'title' in data:
                notice.title = data['title']
            if 'description' in data:
                notice.description = data['description']

            if photo_list := data.get("photo"):
                # 建議把檔名規格化，才不會多次 PUT 造成檔名衝突
                filename = f"{notice.crane_id}_{notice.notice_date.strftime('%Y%m%d')}"
                photos_path = save_photos(filename, photo_list, NOTICE_DIR)
                notice.photo = json.dumps(photos_path)

            db.session.commit()
            return {"status": "0", "result": "注意事項已成功更新"}, 200

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0] if e.args else str(e)
            logger.warning(f"Update Notice Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400
        
    @jwt_required()
    @handle_request_exception
    def delete(self, notice_id):
        """
        刪除單筆 Notice
        """
        try:
            notice = CraneNotice.query.get(notice_id)
            if notice is None:
                return {"status": "1", "result": "找不到指定的注意事項"}, 404
            user = User.query.get(get_jwt_identity())
            if user.permission < 2:
                return {"status": "1", "result": "使用者權限不足"}, 403
            notice.is_deleted = True
            notice.updated_by = user.id

            # 如果有照片，則刪除照片檔案
            if notice.photo:
                delete_photo_file(notice.photo, NOTICE_DIR)
            
            db.session.commit()
            return {"status": "0", "result": "Crane notice deleted."}, 200

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0] if e.args else str(e)
            logger.warning(f"Delete Notice Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400


@api_test.route("/api/notice-colors", methods=["GET", "POST"])
class NoticeColorList(Resource):
    """
    GET  : 取得所有狀態與顏色 (dict)
    POST : 新增一筆狀態與顏色
    """

    @jwt_required()
    @handle_request_exception
    def get(self):
        rows = NoticeColor.query.all()
        result: dict[str, str] = {}
        for r in rows:
            result.update(r.as_dict())
        return {"status": "0", "result": result}, 200

    @api.expect(notice_color_model)
    @jwt_required()
    @handle_request_exception
    def post(self):
        data = api.payload or {}
        status_name: str | None = data.get("status_name")
        color: str | None = data.get("color")

        if not (status_name and color):
            return {"status": "1", "result": "缺少 status_name 或 color"}, 400
        
        if not re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", color):
            return {"status": "1", "result": "色碼格式錯誤 (#FFF 或 #FFFFFF)"}, 400

        # 同名狀態不得重複
        if NoticeColor.query.filter_by(status=status_name).first():
            return {"status": "1", "result": "有相同的狀態已經存在"}, 409

        nc = NoticeColor(status=status_name, color=color)
        db.session.add(nc)
        db.session.commit()
        return {"status": "0", "result": f"已新增 {status_name} → {color}"}, 201

# -----------------------------------
#  Maintenance (CraneMaintenance) GET/POST API
# -----------------------------------
@api_test.route('/api/cranes/<int:crane_id>/maintenances', methods=['GET', 'POST'])
class Create_maintenance(Resource):
    """
    GET: 取得某台吊車的所有維修記錄
    POST: 為某台吊車新增維修記錄
    """
    @jwt_required()
    @handle_request_exception
    def get(self, crane_id):
        """
        查詢某台吊車的維修列表
        """
        try:
            user  = User.query.get(get_jwt_identity())
            if user is None:
                return {"status": "1", "result": "使用者不存在"}, 403
            
            crane = Crane.query.get(crane_id)
            if crane is None:
                return {"status": "1", "result": f"找不到 ID 為 {crane_id} 的吊車"}, 404

            maintenances = (
                CraneMaintenance.query
                .filter(
                    CraneMaintenance.crane_id == crane_id,
                    CraneMaintenance.is_deleted == False
                )
                .order_by(CraneMaintenance.maintenance_date.desc())
                .all()
            )

            result = []
            for m in maintenances:
                raw = m.photo or []                      # None → []
                photo_list = json.loads(raw) if isinstance(raw, str) else raw
                record = {
                    "id":               m.id,
                    "maintenance_date": m.maintenance_date.isoformat(),
                    "title":            m.title,
                    "note":             m.note,
                    "material":         m.material,
                    "has_photo":        bool(photo_list)
                }
                if user.permission == 2:          # 最高權限看全部
                    record.update({
                        "vendor":       m.vendor,
                        "vendor_cost":  float(m.vendor_cost) if m.vendor_cost else None,
                        "parts_vendor": m.parts_vendor,
                        "parts_cost":   float(m.parts_cost) if m.parts_cost else None,
                    })
                result.append(record)
            return {"status": "0", "result": result}, 200

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0] if e.args else str(e)
            logger.warning(f"Get Maintenance Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400

    @jwt_required()
    @handle_request_exception
    @api_ns.expect(add_maintenance_payload)
    @api_ns.marshal_with(general_output_payload)
    def post(self, crane_id):
        """
        新增維修記錄
        """
        try:
            user = User.query.get(get_jwt_identity())
            if user is None:
                return {"status": "1", "result": "使用者不存在"}, 403
            elif user.permission == 0:
                return {"status": "1", "result": "使用者權限不足"}, 403

            data = api_ns.payload
            title    = data.get("title")
            note     = data.get("note")
            material = data.get("material")
            
            if not title:
                return {"status": 1, "result": "缺少標題"}, 400

            try:
                maint_date = datetime.strptime(
                    data.get("maintenance_date") or datetime.now(tz).strftime("%Y-%m-%d"),
                    "%Y-%m-%d"
                ).date()
            except ValueError:
                return {"status": 1, "result": "maintenance_date 格式錯誤，須 YYYY-MM-DD"}, 400
            
            if user.permission < 2 and any(
                data.get(k) for k in ["vendor", "vendor_cost", "parts_vendor", "parts_cost"]
            ):
                return {
                    "status": 1,
                    "result": "中/低權限不得填寫金額或廠商欄位"
                }, 403

            maintenance = CraneMaintenance(
                crane_id=crane_id,
                maintenance_date=maint_date,
                title=title,
                note=note,
                material=material,
                created_by=user.id
            )
            if user.permission == 2:
                maintenance.vendor        = data.get("vendor")
                maintenance.vendor_cost   = data.get("vendor_cost")
                maintenance.parts_vendor  = data.get("parts_vendor")
                maintenance.parts_cost    = data.get("parts_cost")

            db.session.add(maintenance)
            db.session.flush()

            if photo_list := data.get("photo"): 
                photos_path = save_photos(title, photo_list, MAINTANCE_DIR)
                maintenance.photo = json.dumps(photos_path)

            db.session.commit()
            return {"status": "0", "result": "拖車維修紀錄已成功創建"}, 200

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0] if e.args else str(e)
            logger.warning(f"Add Maintenance Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400


@api_test.route('/api/maintenances/<int:maintenance_id>', methods=['GET', 'PUT', 'DELETE'])
class Maintenance(Resource):
    """
    針對單筆維修記錄的 查詢 / 更新 / 刪除
    """

    @jwt_required()
    @handle_request_exception
    def get(self, maintenance_id):
        """
        取得單筆維修記錄
        """
        try:
            m = (
                CraneMaintenance.query.filter_by(id=maintenance_id, is_deleted=False)
                .first()
            )
            if m is None:
                return {"status": "1", "result": "找不到指定的維修記錄"}, 404
            user = User.query.get(get_jwt_identity())
            if user is None:
                return {"status": "1", "result": "使用者不存在"}, 403
            permission = user.permission

            data = {
                "id": m.id,
                "crane_id": m.crane_id,
                "maintenance_date": m.maintenance_date.isoformat(),
                "photo": photo_path_to_base64(m.photo) if m.photo else None,
            }
            if permission == 2:      # 最高權限補全敏感欄位
                data.update({
                    "vendor":       m.vendor,
                    "vendor_cost":  float(m.vendor_cost) if m.vendor_cost else None,
                    "parts_vendor": m.parts_vendor,
                    "parts_cost":   float(m.parts_cost) if m.parts_cost else None,
                })
            return {"status": "0", "result": data}, 200

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0] if e.args else str(e)
            logger.warning(f"Get Maintenance Detail Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400

    @jwt_required()
    @handle_request_exception
    @api_ns.expect(add_maintenance_payload)
    @api_ns.marshal_with(general_output_payload)
    def put(self, maintenance_id):
        """
        更新單筆維修記錄
        """
        try:
            user = User.query.get(get_jwt_identity())
            if user is None:
                return {"status": "1", "result": "使用者不存在"}, 403
            elif user.permission == 0:
                return {"status": 1, "result": "使用者權限不足"}, 403
            
            

            maintaince = CraneMaintenance.query.get(maintenance_id)
            if maintaince is None:
                return {"status": "1", "result": "找不到指定的維修記錄"}, 404
            data = api_ns.payload or {}

            if 'maintenance_date' in data and data['maintenance_date']:
                try:
                    maintaince.maintenance_date = datetime.strptime(
                        data["maintenance_date"], "%Y-%m-%d"
                    ).date()
                except ValueError:
                    return {"status": 1, "result": "maintenance_日期格式錯誤 YYYY-MM-DD"}, 400
                
            # 基礎欄位（中以上皆可改）
            for k in ("title", "note", "material"):
                if k in data:
                    setattr(maintaince, k, data[k])

            if photo_list := data.get("photo"): 
                photos_path = save_photos(maintaince.title, photo_list, MAINTANCE_DIR)
                maintaince.photo = json.dumps(photos_path)



            # 最高權限才能改敏感欄位
            if user.permission == 2:
                for k in ("vendor", "vendor_cost", "parts_vendor", "parts_cost"):
                    if k in data:
                        setattr(maintaince, k, data[k])
            elif any(data.get(x) is not None for x in ("vendor", "vendor_cost", "parts_vendor", "parts_cost")):
                return {"status": 1, "result": "中/低權限不得修改金額或廠商欄位"}, 403

            db.session.commit()
            return {"status": "0", "result": "吊車維修紀錄已成功更新"}, 200

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0] if e.args else str(e)
            logger.warning(f"Update Maintenance Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400
        
    @jwt_required()
    @handle_request_exception
    def delete(self, maintenance_id):
        """
        刪除單筆維修記錄
        """
        try:
            user = User.query.get(get_jwt_identity())
            if user is None:
                return {"status": "1", "result": "使用者不存在"}, 403
            if user.permission < 2:
                return {"status": 1, "result": "使用者權限不足"}, 403
            maintaince = CraneMaintenance.query.get(maintenance_id)
            if maintaince is None:
                return {"status": "1", "result": "找不到指定的維修記錄"}, 404
            # 如果有照片，則刪除照片檔案
            if maintaince.photo:
                delete_photo_file(maintaince.photo, MAINTANCE_DIR)
            
            maintaince.is_deleted = True
            db.session.commit()
            return{"status": "0", "result": "吊車的維修紀錄已成功刪除"}, 200

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0] if e.args else str(e)
            logger.warning(f"Delete Maintenance Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400


        

