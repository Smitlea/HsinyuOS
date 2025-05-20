import datetime
import pytz

from flask_restx import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Crane, User, CraneUsage, CraneNotice, CraneMaintenance
from payload import api_ns, api_crane, api_test, api_notice, add_crane_payload, general_output_payload, add_usage_payload, add_notice_payload, add_maintenance_payload
from util import handle_request_exception
from logger import logging

from payload import api
logger = logging.getLogger(__file__)

tz = pytz.timezone('Asia/Taipei')

@api_crane.route('/api/cranes', methods=['GET', 'POST'])
class Create_crane(Resource):
    @handle_request_exception
    @jwt_required()
    def get(self):
        try:
            cranes = Crane.query.all()
            result = []
            for crane in cranes:
                # 計算累計時數
                usages = CraneUsage.query.filter_by(crane_id=crane.id).all()
                total_usage = crane.initial_hours + sum(u.daily_hours for u in usages)

                # 判斷是否超過臨界值
                threshold = 500 if crane.crane_type == "履帶" else 1000
                alert = total_usage > threshold

                result.append({
                    "id": crane.id,
                    "crane_number": crane.crane_number,
                    "crane_type": crane.crane_type,
                    "location": crane.location,
                    "photo": crane.photo,
                    "total_usage_hours": total_usage,
                    "alert": alert  
                })
            return {"status": "0", "result": result}, 200
        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0]
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
            location = data.get('location')
            photo = data.get('photo')
            
            if Crane.query.filter_by(crane_number=crane_number).first():
                return {'status':'1', 'result': '拖車已經存在了'}

            user = User.query.get_or_404(get_jwt_identity())

            if user.permission < 0:
                return {'status':'1', 'result': '使用者權限不足'}

            new_crane = Crane(
                crane_number=crane_number,
                crane_type=crane_type,
                initial_hours=initial_hours,
                location=location,
                photo=photo
            )

            db.session.add(new_crane)
            db.session.commit()
            return {"status": '0', "result": "Crane created successfully"}, 201
        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0]
            logger.warning(f"Add Crane Error: [{error_class}] detail: {detail}")
            return {'status': 1, 'result': error_class, "error": e.args}, 400
        


    

@api_crane.route('/api/cranes/<int:crane_id>', methods=['GET', 'PUT', 'DELETE'])
class Crane_detail(Resource):
    @handle_request_exception
    @jwt_required()
    def get(self, crane_id):
        try:
            crane = Crane.query.get_or_404(crane_id)
            usages = CraneUsage.query.filter_by(crane_id=crane_id).all()
            total_usage = crane.initial_hours + sum(u.daily_hours for u in usages)
            threshold = 500 if crane.crane_type == "履帶" else 1000
            alert = total_usage > threshold

            data = {
                "id": crane.id,
                "crane_number": crane.crane_number,
                "crane_type": crane.crane_type,
                "location": crane.location,
                "photo": crane.photo,
                "total_usage_hours": total_usage,
                "alert": alert
            }
            return {"status": '0', "result": data}, 200
        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0]
            logger.warning(f"Get Crane Detail Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400
        
    @handle_request_exception
    @jwt_required()
    @api.expect(add_crane_payload)
    @api.marshal_with(general_output_payload)
    def put(self, crane_id):
        try:
            crane = Crane.query.get_or_404(crane_id)
            data = api.payload
            crane.crane_number = data.get('crane_number', crane.crane_number)
            crane.crane_type = data.get('crane_type', crane.crane_type)
            crane.location = data.get('location', crane.location)
            crane.photo = data.get('photo', crane.photo)
            
            if 'initial_hours' in data:
                crane.initial_hours = data['initial_hours']

            db.session.commit()
            return {"status": '0', "result": "Crane updated successfully."}, 200
        except Exception as e:
            error_class = e.__class__.__name__
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
            # 若需要確認 crane_id 存在，可再引用 Crane.query.get_or_404(crane_id)
            usages = CraneUsage.query.filter_by(crane_id=crane_id).order_by(CraneUsage.usage_date.desc()).all()
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
            detail = e.args[0]
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
            user = User.query.get_or_404(get_jwt_identity())
            if user.permission < 0:
                return {"status": "1", "result": "使用者權限不足"}

            # 判斷日期格式或預設值
            if not usage_date:
                usage_date = datetime.datetime.now(tz).date()
            else:
                usage_date = datetime.datetime.strptime(usage_date, "%Y-%m-%d").date()

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
            detail = e.args[0]
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
            usage = CraneUsage.query.get_or_404(usage_id)
            data = {
                "id": usage.id,
                "crane_id": usage.crane_id,
                "usage_date": usage.usage_date.isoformat(),
                "daily_hours": usage.daily_hours
            }
            return {"status": "0", "result": data}, 200

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0]
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
                usage.usage_date = datetime.datetime.strptime(data['usage_date'], "%Y-%m-%d").date()
            if 'daily_hours' in data:
                usage.daily_hours = data['daily_hours']

            db.session.commit()
            return {"status": "0", "result": "Usage record updated."}, 200

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0]
            logger.warning(f"Update Usage Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400

    @handle_request_exception
    @jwt_required()
    def delete(self, usage_id):
        """
        刪除單筆使用紀錄
        """
        try:
            usage = CraneUsage.query.get_or_404(usage_id)
            db.session.delete(usage)
            db.session.commit()
            return {"status": "0", "result": "Usage record deleted."}, 200

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0]
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

    @handle_request_exception
    @jwt_required()
    def get(self, crane_id):
        """
        查詢 notice 列表
        """
        try:
            notices = CraneNotice.query.filter_by(crane_id=crane_id).order_by(CraneNotice.notice_date.desc()).all()
            result = []
            for n in notices:
                result.append({
                    "id": n.id,
                    "notice_date": n.notice_date.isoformat(),
                    "status": n.status,
                    "title": n.title,
                    "description": n.description
                })
            return {"status": "0", "result": result}, 200

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0]
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
            user = User.query.get_or_404(get_jwt_identity())
            if user.permission < 0:
                return {"status": "1", "result": "使用者權限不足"}

            data = api_ns.payload
            notice_date = data.get('notice_date')
            status = data.get('status')
            title = data.get('title')
            description = data.get('description')

            if not notice_date:
                notice_date = datetime.datetime.now(tz).date()
            else:
                notice_date = datetime.datetime.strptime(notice_date, "%Y-%m-%d").date()

            new_notice = CraneNotice(
                crane_id=crane_id,
                notice_date=notice_date,
                status=status,
                title=title,
                description=description
            )
            db.session.add(new_notice)
            db.session.commit()
            return {"status": "0", "result": "Crane notice created."}, 201

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0]
            logger.warning(f"Add Notice Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400


@api_notice.route('/api/notices/<int:notice_id>', methods=['GET', 'PUT', 'DELETE'])
class Notice(Resource):
    """
    針對單筆 Notice 的 查詢 / 更新 / 刪除
    """

    @handle_request_exception
    @jwt_required()
    def get(self, notice_id):
        """
        取得單筆 Notice 資訊
        """
        try:
            notice = CraneNotice.query.get_or_404(notice_id)
            data = {
                "id": notice.id,
                "crane_id": notice.crane_id,
                "notice_date": notice.notice_date.isoformat(),
                "status": notice.status,
                "title": notice.title,
                "description": notice.description
            }
            return {"status": "0", "result": data}, 200

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0]
            logger.warning(f"Get Notice Detail Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400

    @handle_request_exception
    @jwt_required()
    @api_ns.expect(add_notice_payload)
    @api_ns.marshal_with(general_output_payload)
    def put(self, notice_id):
        """
        更新單筆 Notice
        """
        try:
            notice = CraneNotice.query.get_or_404(notice_id)
            data = api_ns.payload

            if 'notice_date' in data and data['notice_date']:
                notice.notice_date = datetime.datetime.strptime(data['notice_date'], "%Y-%m-%d").date()
            if 'status' in data:
                notice.status = data['status']
            if 'title' in data:
                notice.title = data['title']
            if 'description' in data:
                notice.description = data['description']

            db.session.commit()
            return {"status": "0", "result": "Crane notice updated."}, 200

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0]
            logger.warning(f"Update Notice Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400

    @handle_request_exception
    @jwt_required()
    def delete(self, notice_id):
        """
        刪除單筆 Notice
        """
        try:
            notice = CraneNotice.query.get_or_404(notice_id)
            db.session.delete(notice)
            db.session.commit()
            return {"status": "0", "result": "Crane notice deleted."}, 200

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0]
            logger.warning(f"Delete Notice Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400


# -----------------------------------
#  Maintenance (CraneMaintenance) 相關 API
# -----------------------------------
@api_test.route('/api/cranes/<int:crane_id>/maintenances', methods=['GET', 'POST'])
class Create_maintenance(Resource):
    """
    GET: 取得某台吊車的所有維修記錄
    POST: 為某台吊車新增維修記錄
    """

    @handle_request_exception
    @jwt_required()
    def get(self, crane_id):
        """
        查詢某台吊車的維修列表
        """
        try:
            maintenances = CraneMaintenance.query.filter_by(crane_id=crane_id).order_by(CraneMaintenance.maintenance_date.desc()).all()
            result = []
            for m in maintenances:
                result.append({
                    "id": m.id,
                    "maintenance_date": m.maintenance_date.isoformat(),
                    "field1": m.field1,
                    "field2": m.field2,
                    "field3": m.field3
                })
            return {"status": "0", "result": result}, 200

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0]
            logger.warning(f"Get Maintenance Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400

    @handle_request_exception
    @jwt_required()
    @api_ns.expect(add_maintenance_payload)
    @api_ns.marshal_with(general_output_payload)
    def post(self, crane_id):
        """
        新增維修記錄
        """
        try:
            user = User.query.get_or_404(get_jwt_identity())
            if user.permission < 0:
                return {"status": "1", "result": "使用者權限不足"}

            data = api_ns.payload
            maintenance_date = data.get('maintenance_date')
            field1 = data.get('field1')
            field2 = data.get('field2')
            field3 = data.get('field3')

            if not maintenance_date:
                maintenance_date = datetime.datetime.now(tz).date()
            else:
                maintenance_date = datetime.datetime.strptime(maintenance_date, "%Y-%m-%d").date()

            new_maintenance = CraneMaintenance(
                crane_id=crane_id,
                maintenance_date=maintenance_date,
                field1=field1,
                field2=field2,
                field3=field3
            )
            db.session.add(new_maintenance)
            db.session.commit()

            return {"status": "0", "result": "Crane maintenance record created."}, 201

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0]
            logger.warning(f"Add Maintenance Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400


@api_test.route('/api/maintenances/<int:maintenance_id>', methods=['GET', 'PUT', 'DELETE'])
class Maintenance(Resource):
    """
    針對單筆維修記錄的 查詢 / 更新 / 刪除
    """

    @handle_request_exception
    @jwt_required()
    def get(self, maintenance_id):
        """
        取得單筆維修記錄
        """
        try:
            m = CraneMaintenance.query.get_or_404(maintenance_id)
            data = {
                "id": m.id,
                "crane_id": m.crane_id,
                "maintenance_date": m.maintenance_date.isoformat(),
                "field1": m.field1,
                "field2": m.field2,
                "field3": m.field3
            }
            return {"status": "0", "result": data}, 200

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0]
            logger.warning(f"Get Maintenance Detail Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400

    @handle_request_exception
    @jwt_required()
    @api_ns.expect(add_maintenance_payload)
    @api_ns.marshal_with(general_output_payload)
    def put(self, maintenance_id):
        """
        更新單筆維修記錄
        """
        try:
            m = CraneMaintenance.query.get_or_404(maintenance_id)
            data = api_ns.payload

            if 'maintenance_date' in data and data['maintenance_date']:
                m.maintenance_date = datetime.datetime.strptime(data['maintenance_date'], "%Y-%m-%d").date()
            if 'field1' in data:
                m.field1 = data['field1']
            if 'field2' in data:
                m.field2 = data['field2']
            if 'field3' in data:
                m.field3 = data['field3']

            db.session.commit()
            return {"status": "0", "result": "Crane maintenance record updated."}, 200

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0]
            logger.warning(f"Update Maintenance Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400

    @handle_request_exception
    @jwt_required()
    def delete(self, maintenance_id):
        """
        刪除單筆維修記錄
        """
        try:
            m = CraneMaintenance.query.get_or_404(maintenance_id)
            db.session.delete(m)
            db.session.commit()
            return{"status": "0", "result": "Crane maintenance record deleted."}, 200

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0]
            logger.warning(f"Delete Maintenance Error: [{error_class}] detail: {detail}")
            return {"status": "1", "result": error_class, "error": e.args}, 400


        

