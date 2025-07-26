from datetime import datetime
import pytz

from flask import request
from flask_restx import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import selectinload  
from static.models import db, Crane, User, DailyTask, WorkRecord, TaskMaintenance, ConstructionSite, CraneAssignment

from static.payload import (
    api_ns, add_task_payload,
    general_output_payload, 
    add_task_maint_payload, 
    work_record_input_payload
)
from static.util import handle_request_exception
from static.logger import logging

logger = logging.getLogger(__file__)
tz = pytz.timezone('Asia/Taipei')

@api_ns.route("/api/daily-tasks", methods=["GET", "POST"])
class DailyTaskList(Resource):
    """GET 取得列表；POST 新增每日任務"""

    @jwt_required()
    @handle_request_exception
    def get(self):
        """
        回傳所有 DailyTask（未加篩選，可視需求加 querystring filter）
        """
        tasks = (
            DailyTask.query
            .filter(DailyTask.is_deleted.is_(False))
            .options(
                selectinload(DailyTask.crane),
                selectinload(DailyTask.site),
            )
            .order_by(DailyTask.task_date.desc())
            .all()
        )
        result = []
        for t in tasks:
            result.append({
                "id":           t.id,
                "creator":      t.updated_by_nickname,
                "vendor":       t.vendor,
                "location":     t.site.location if t.site else None,
                "task_date":    t.task_date.isoformat(),
                "crane_number": t.crane.crane_number if t.crane else None,
                "work_time":    t.work_time,
                "note":         t.note,
            })
        return {"status": "0", "result": result}, 200

    @jwt_required()
    @handle_request_exception
    @api_ns.expect(add_task_payload)
    @api_ns.marshal_with(general_output_payload)
    def post(self):
        """
        新增一筆 DailyTask
        """
        data = api_ns.payload or {}
        # --- 權限驗證 ---
        user = User.query.get(get_jwt_identity())
        if not user:
            return {"status": 1, "result": "使用者不存在"}, 403

        vendor  = data.get("vendor")
        site_id = data.get("site_id")
        crane_number= data.get("crane_number")
        work_time = data.get("work_time")
        note    = data.get("note")

        try:
            task_date = datetime.strptime(
                data.get("task_date") or datetime.now(tz).strftime("%Y-%m-%d"),
                "%Y-%m-%d"
            ).date()
        except ValueError:
            return {"status": 1, "result": "task_date 格式錯誤，須 YYYY-MM-DD"}, 400

        # 查工地
        site = ConstructionSite.query.get(site_id)
        if not site:
            return {"status": 1, "result": "找不到工地"}, 404
        # 查吊車
        crane = Crane.query.filter_by(crane_number=crane_number).first()
        if not crane:
            return {"status": 1, "result": "找不到對應車號"}, 404
        
        #這裡是額外的驗證功能 暫不考慮
        # 1. 取得當天的有效派工 (CraneAssignment)
        assign = (
            CraneAssignment.query
            .filter(
                CraneAssignment.crane_id == crane.id,
                CraneAssignment.start_date <= task_date,
                db.or_(CraneAssignment.end_date == None,
                    CraneAssignment.end_date >= task_date)
            )
            .first()
        )

        # 2. 若有派工且工地不同 => 回 409
        if assign and assign.site_id != site_id:
            return {
                "status": 1,
                "result": f"車號 {crane_number} 當 {task_date} 已派至其他工地，無法重複分配"
            }, 409
        

        # 寫入
        task = DailyTask(
            task_date = task_date,
            vendor    = vendor,
            work_time = work_time,
            note      = note,
            site      = site,
            crane     = crane,
            created_by= user.id,
            updated_by= user.id
        )
        db.session.add(task)
        db.session.commit()
        return {"status": "0", "result": "工作紀錄成功創建"}, 200


# ---------------------------------------
#  單筆 Daily-Task CRUD
# ---------------------------------------
@api_ns.route("/api/daily-tasks/<int:task_id>", methods=["GET", "PUT", "DELETE"])
class DailyTaskDetail(Resource):
    """單筆 Task CRUD（PUT/DELETE 可依專案權限需求開關）"""

    @jwt_required()
    @handle_request_exception
    def get(self, task_id):
        task = DailyTask.query.filter_by(id=task_id, is_deleted=False).first()
        if not task:
            return {"status": 1, "result": "找不到工作紀錄"}, 404
        data = {
            "id":           task.id,
            "vendor":       task.vendor,
            "location":     task.site.location if task.site else None,
            "task_date":    task.task_date.isoformat(),
            "site_id":      task.site.id if task.site else None,
            "crane_number": task.crane.crane_number if task.crane else None,
            "work_time":    task.work_time,
            "note":         task.note,
        }
        return {"status": "0", "result": data}, 200
    
    @jwt_required()
    @handle_request_exception
    @api_ns.expect(add_task_payload)
    @api_ns.marshal_with(general_output_payload)
    def put(self, task_id):
        """
        更新指定 Task
        """
        data = api_ns.payload
        task = DailyTask.query.filter_by(id=task_id, is_deleted=False).first()
        if not task:
            return {"status": 1, "result": "找不到 Task"}, 404

        # 權限驗證
        user = User.query.get(get_jwt_identity())
        if not user:
            return {"status": 1, "result": "使用者不存在"}, 403

        # 驗證輸入
        vendor  = data.get("vendor")
        site_id = data.get("site_id")
        crane_number= data.get("crane_number")
        work_time = data.get("work_time")
        note    = data.get("note")

        # 日期
        try:
            task_date = datetime.strptime(
                data.get("task_date") or datetime.now(tz).strftime("%Y-%m-%d"),
                "%Y-%m-%d"
            ).date()
        except ValueError:
            return {"status": 1, "result": "task_date 格式錯誤，須 YYYY-MM-DD"}, 400

        # 查工地
        site = ConstructionSite.query.get(site_id)
        if not site:
            return {"status": 1, "result": "找不到工地"}, 404
        # 查吊車
        crane = Crane.query.filter_by(crane_number=crane_number).first()
        if not crane:
            return {"status": 1, "result": "找不到對應車號"}, 404

        #這裡是額外的驗證功能 暫不考慮
        # 1. 取得當天的有效派工 (CraneAssignment)
        assign = (
            CraneAssignment.query
            .filter(
                CraneAssignment.crane_id == crane.id,
                CraneAssignment.start_date <= task_date,
                db.or_(CraneAssignment.end_date == None,
                    CraneAssignment.end_date >= task_date)
            )
            .first()
        )

        # 2. 若有派工且工地不同 => 回 409
        if assign and assign.site_id != site_id:
            return {
                "status": 1,
                "result": f"車號 {crane_number} 當 {task_date} 已派至其他工地，無法重複分配"
            }, 409

        # 更新
        task.task_date = task_date
        task.vendor    = vendor
        task.work_time = work_time
        task.note      = note
        task.site      = site
        task.crane     = crane
        task.updated_by = user.id
        db.session.commit()
        return {"status": "0", "result": "工作紀錄成功更新"}, 200
    
    @jwt_required()
    @handle_request_exception
    @api_ns.marshal_with(general_output_payload)
    def delete(self, task_id):
        """
        刪除指定 Task
        """
        task = DailyTask.query.filter_by(id=task_id, is_deleted=False).first()
        if not task:
            return {"status": 1, "result": "找不到 Task"}, 404

        # 權限驗證（可依專案需求調整）
        user = User.query.get(get_jwt_identity())
        if not user:
            return {"status": 1, "result": "使用者不存在"}, 403
        if user.permission < 0:
            return {"status": 1, "result": "權限不足，無法刪除 Task"}, 403
        # 標記為已刪除
        task.is_deleted = True
        task.updated_by = user.id

        db.session.commit()
        return {"status": "0", "result": "維修紀錄已成功刪除"}, 200


# -------------------------------
#  保養紀錄
# -------------------------------

@api_ns.route("/api/daily-tasks/maintenances", methods=["GET", "POST"])
class TaskMaintenanceList(Resource):
    """GET / POST 保養紀錄（只含日期＋字串敘述）"""

    @jwt_required()
    @handle_request_exception
    def get(self):
        """
        取得保養紀錄清單  
        - 一般員工 (permission <= 1)：只能看到自己建立的  
        - 主管     (permission > 1)：可以看到全部
        """

        user = User.query.get(get_jwt_identity())
        

        query = TaskMaintenance.query.filter(TaskMaintenance.is_deleted == False)
        if user.permission <= 1:
            query = query.filter(TaskMaintenance.created_by == user.id)

        maintaince = query.order_by(TaskMaintenance.record_date.desc()).all()
        result = [
            {
                "id":              m.id,
                "maintenance_date": m.record_date.isoformat(),
                "creator":          m.nickname,
                "description":     m.description,
            }
            for m in maintaince
        ]

        return {"status": "0", "result": result}, 200

    @jwt_required()
    @handle_request_exception
    @api_ns.expect(add_task_maint_payload)
    @api_ns.marshal_with(general_output_payload)
    def post(self):

        data = api_ns.payload
        user = User.query.get(get_jwt_identity())
        if not user:
            return {"status": 1, "result": "使用者不存在"}, 403
        # 解析日期
        try:
            record = datetime.strptime(
                data.get("maintenance_date") or datetime.now(tz).strftime("%Y-%m-%d"), "%Y-%m-%d"
            ).date()
        except ValueError:
            return {"status": 1, "result": "maintenance_date 格式錯誤 YYYY-MM-DD"}, 400

        if not data.get("description"):
            return {"status": 1, "result": "缺少 description"}, 400

        m = TaskMaintenance(
            record_date = record,
            description = data["description"],
            created_by = user.id,
            updated_by = user.id
        )
        db.session.add(m)
        db.session.commit()
        return {"status": "0", "result": "成功創建保養紀錄"}, 201
    
# ---------------------------------------
#  單筆 Task‑Maintenance CRUD
# ---------------------------------------
@api_ns.route("/api/daily-tasks/maintenances/<int:maint_id>", methods=["GET", "PUT", "DELETE"])
class TaskMaintenanceDetail(Resource):
    """單筆保養紀錄 CRUD"""

    # ----------  READ  ----------
    @jwt_required()
    @handle_request_exception
    def get(self, maint_id):
        """取得指定保養紀錄"""
        m = TaskMaintenance.query.filter_by(
            id=maint_id, is_deleted=False
        ).first()
        if not m:
            return {"status": 1, "result": "找不到保養紀錄"}, 404

        user = User.query.get(get_jwt_identity())
        if user.permission <= 1 and m.created_by != user.id:
            return {"status": 1, "result": "權限不足"}, 403

        data = {
            "id":               m.id,
            "maintenance_date": m.record_date.isoformat(),
            "creator":          m.nickname,
            "description":      m.description,
        }
        return {"status": "0", "result": data}, 200

    # ----------  UPDATE  ----------
    @jwt_required()
    @handle_request_exception
    @api_ns.expect(add_task_maint_payload)
    @api_ns.marshal_with(general_output_payload)
    def put(self, maint_id):
        """更新指定保養紀錄"""
        m = TaskMaintenance.query.filter_by(
            id=maint_id, is_deleted=False
        ).first()
        if not m:
            return {"status": 1, "result": "找不到保養紀錄"}, 404

        user = User.query.get(get_jwt_identity())
        if user.permission <= 1 and m.created_by != user.id:
            return {"status": 1, "result": "權限不足"}, 403

        data = api_ns.payload or {}
        # 日期驗證（允許不改）
        if data.get("maintenance_date"):
            try:
                m.record_date = datetime.strptime(
                    data["maintenance_date"], "%Y-%m-%d"
                ).date()
            except ValueError:
                return {"status": 1, "result": "maintenance_date 格式錯誤 YYYY-MM-DD"}, 400

        # 內容必填驗證
        if "description" in data and not data["description"]:
            return {"status": 1, "result": "缺少 description"}, 400
        m.description = data.get("description", m.description)

        m.updated_by = user.id
        db.session.commit()
        return {"status": "0", "result": "保養紀錄已更新"}, 200

    # ----------  DELETE  ----------
    @jwt_required()
    @handle_request_exception
    @api_ns.marshal_with(general_output_payload)
    def delete(self, maint_id):
        """刪除指定保養紀錄（軟刪除）"""
        m = TaskMaintenance.query.filter_by(
            id=maint_id, is_deleted=False
        ).first()
        if not m:
            return {"status": 1, "result": "找不到保養紀錄"}, 404

        user = User.query.get(get_jwt_identity())
        if user.permission <= 1 and m.created_by != user.id:
            return {"status": 1, "result": "權限不足"}, 403

        m.is_deleted = True
        m.updated_by = user.id
        db.session.commit()
        return {"status": "0", "result": "保養紀錄已刪除"}, 200


@api_ns.route("/api/extravtory-workrecord", methods=["GET", "POST"])
class ExtravtoryWorkRecord(Resource):
    """
    怪手工作紀錄列表與新增
    GET 取得工作紀錄列表
    POST 新增一筆工作紀錄
    """
    @jwt_required()
    @handle_request_exception
    def get(self):
        """
        回傳工作紀錄列表
        """
        records = WorkRecord.query.filter_by(
            is_deleted=False
        ).order_by(WorkRecord.record_date.desc()).all()
        result = []

        for r in records:
            result.append({
                "id": r.id,
                "creator": r.updated_by_nickname,
                "location":     r.site.location if r.site else None,
                "crane_number": r.crane.crane_number if r.crane else None,
                "record_date": r.record_date.isoformat(),
                "vendor": r.vendor,
                "qty_120": r.qty_120,
                "qty_200": r.qty_200,
                "assistants": r.assistants,
            })
        return {"status": "0", "result": result}, 200

    @jwt_required()
    @handle_request_exception
    @api_ns.expect(work_record_input_payload)
    def post(self):
        """
        新增一筆工作紀錄
        """
        data = request.json
        # 權限驗證
        site_id = data.get("site_id")
        crane_number= data.get("crane_number")
        site = ConstructionSite.query.get(site_id)
        if not site:
            return {"status": 1, "result": "找不到工地"}, 404
        
        crane = Crane.query.filter_by(crane_number=crane_number).first()
        if not crane:
            return {"status": 1, "result": "找不到對應車號"}, 404
        
        user = User.query.get(get_jwt_identity())
        if not user:
            return {"status": 1, "result": "使用者不存在"}, 403

        # 驗證輸入
        vendor = data.get("vendor")
        if not vendor:
            return {"status": 1, "result": "缺乏廠商欄位"}, 400
        try:
            qty_120 = int(data.get("qty_120", 0))
            qty_200 = int(data.get("qty_200", 0))
            assert qty_120 >= 0 and qty_200 >= 0
        except (ValueError, AssertionError):
            return {"status": 1, "result": "qty_120 / qty_200 必須為非負整數"}, 40
        
        assistants = data.get("assistants", [])
        if len(assistants) > 4:
            return {"status": 1, "result": "輔助人員不能超過4個或是非user.id'數字'陣列型態"}, 400

        # 日期處理
        try:
            record_date = datetime.strptime(
                data.get("record_date") or datetime.now(tz).strftime("%Y-%m-%d"),
                "%Y-%m-%d"
            ).date()
        except ValueError:
            return {"status": 1, "result": "record_date 格式錯誤，須 YYYY-MM-DD"}, 400

        # 新增工作紀錄
        record = WorkRecord(
            record_date=record_date,
            site      = site,
            crane     = crane,
            vendor=vendor,
            qty_120=qty_120,
            qty_200=qty_200,
            assistants=assistants,  
            created_by=user.id,
            updated_by=user.id
        )
        db.session.add(record)
        db.session.commit()
        return {"status": "0", "result": "工作紀錄已成功新增"}, 200
    
# ---------------------------------------
#  單筆 Work-Record  CRUD
# ---------------------------------------
@api_ns.route("/api/extravtory-workrecord/<int:record_id>", methods=["GET", "PUT", "DELETE"])
class WorkRecordDetail(Resource):
    """怪手工作紀錄 – 單筆 CRUD"""

    # ─────────────────────────────── GET
    @jwt_required()
    @handle_request_exception
    def get(self, record_id):
        record = WorkRecord.query.filter_by(id=record_id, is_deleted=False).first()
        if not record:
            return {"status": 1, "result": "找不到工作紀錄"}, 404

        return {"status": "0", "result": record.to_dict()}, 200

    # ─────────────────────────────── PUT
    @jwt_required()
    @handle_request_exception
    @api_ns.expect(work_record_input_payload)
    @api_ns.marshal_with(general_output_payload)
    def put(self, record_id):
        data = request.json
        site_id = data.get("site_id")
        crane_number= data.get("crane_number")
        site = ConstructionSite.query.get(site_id)
        if not site:
            return {"status": 1, "result": "找不到工地"}, 404
        crane = Crane.query.filter_by(crane_number=crane_number).first()
        if not crane:
            return {"status": 1, "result": "找不到對應車號"}, 404


        record = WorkRecord.query.filter_by(id=record_id, is_deleted=False).first()
        if not record:
            return {"status": 1, "result": "找不到工作紀錄"}, 404

        # 權限驗證
        user = User.query.get(get_jwt_identity())
        if not user:
            return {"status": 1, "result": "使用者不存在"}, 403

        # ─────── 驗證與轉型 ───────
        vendor = data.get("vendor")
        if not vendor:
            return {"status": 1, "result": "缺乏廠商欄位"}, 400

        try:
            qty_120 = int(data.get("qty_120", 0))
            qty_200 = int(data.get("qty_200", 0))
            assert qty_120 >= 0 and qty_200 >= 0
        except (ValueError, AssertionError):
            return {"status": 1, "result": "qty_120 / qty_200 必須為非負整數"}, 400

        assistants = data.get("assistants", [])
        if len(assistants) > 4:
            return {"status": 1, "result": "輔助人員不能超過 4 個"}, 400

        try:
            record_date = datetime.strptime(
                data.get("record_date") or datetime.now(tz).strftime("%Y-%m-%d"),
                "%Y-%m-%d"
            ).date()
        except ValueError:
            return {"status": 1, "result": "record_date 格式錯誤，須 YYYY-MM-DD"}, 400

        # ─────── 更新欄位 ───────
        record.record_date = record_date
        record.vendor      = vendor
        record.qty_120     = qty_120
        record.qty_200     = qty_200
        record.site        = site
        record.crane       = crane
        record.assistants  = assistants
        record.update_by   = user.id

        db.session.commit()
        return {"status": "0", "result": "工作紀錄成功更新"}, 200

    # ──────────────────────────── DELETE
    @jwt_required()
    @handle_request_exception
    @api_ns.marshal_with(general_output_payload)
    def delete(self, record_id):
        record = WorkRecord.query.filter_by(id=record_id, is_deleted=False).first()
        if not record:
            return {"status": 1, "result": "找不到工作紀錄"}, 404

        user = User.query.get(get_jwt_identity())
        if not user:
            return {"status": 1, "result": "使用者不存在"}, 403
        if user.permission < 0:
            return {"status": 1, "result": "權限不足，無法刪除"}, 403

        # 軟刪除
        record.is_deleted = True
        record.update_by  = user.id
        db.session.commit()
        return {"status": "0", "result": "工作紀錄已成功刪除"}, 200

    

@api_ns.route("/api/available-cranes")
class AvailableCranes(Resource):
    """
    回傳指定日期可用的吊車（未派到其他工地，或已派在同工地）
    GET ?site_id=...&task_date=YYYY-MM-DD
    """
    @jwt_required()
    @handle_request_exception
    def get(self):
        site_id   = request.args.get("site_id")
        task_date = request.args.get("task_date") or datetime.now(tz).strftime("%Y-%m-%d")

        try:
            task_date = datetime.strptime(task_date, "%Y-%m-%d").date()
        except ValueError:
            return {"status": 1, "result": "task_date 格式錯誤 YYYY-MM-DD"}, 400

        # 找出當天有『衝突』的 crane_id
        sub_q = (
            db.session.query(CraneAssignment.crane_id)
            .filter(
                CraneAssignment.start_date <= task_date,
                db.or_(CraneAssignment.end_date == None,
                       CraneAssignment.end_date >= task_date),
                CraneAssignment.site_id != site_id          # ≠ 指定工地才算衝突
            )
        )

        # 可用 = 不在 sub_q 內
        cranes = (
            Crane.query
            .filter(~Crane.id.in_(sub_q))
            .all()
        )
        result = [
            {"id": c.id, "crane_number": c.crane_number, "site_id": c.site_id}
            for c in cranes
        ]
        return {"status": 0, "result": result}, 200
