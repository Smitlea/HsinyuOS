import json
import re

from flask import request
from flask_restx import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.exceptions import BadRequest

from static.payload import (
    api, api_ns, leave_payload, general_output_payload, 
    announcement_payload, announcemnt_color_model
)
from static.models import db, User, Leave, Announcement, SOPVideo, AnnocementColor
from static.util import handle_request_exception, save_photos, delete_photo_file
from static.logger import logging

logger = logging.getLogger(__file__)
PHOTO_DIR = "static/announcement_photos"


@api_ns.route('/api/requestleave', methods=['POST'])
class LeaveRequest(Resource):
    @handle_request_exception
    @api.expect(leave_payload)
    @api.marshal_with(general_output_payload)
    @jwt_required()
    def post(self):
        try:
            data = api.payload
            user_id = User.query.get(get_jwt_identity()).id
            start_date = data.get('start_date')
            end_date = data.get('end_date')
            reason = data.get('reason')
            
            new_leave_request = Leave(user_id=user_id, start_date=start_date, end_date=end_date, reason=reason)
            db.session.add(new_leave_request)
            db.session.commit()
            return {'status':'0', 'result': '新增成功'}
        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0]
            logger.warning(f"Add LeaveRequest Error: [{error_class}] detail: {detail}")
            return {'status':'1', 'result': str(e)}
        
@api_ns.route("/announcements")
class AnnouncementList(Resource):
    @jwt_required()
    @handle_request_exception
    def get(self):
        """列出所有公告（預設不回傳照片）"""
        rows = db.session.scalars(
            db.select(Announcement)
            .where(Announcement.is_deleted == 0)
            .order_by(Announcement.created_at.desc())
        ).all()
        return {"status": "0", "result": [a.to_dict() for a in rows]}, 200

    @jwt_required()
    @handle_request_exception
    @api_ns.expect(announcement_payload)
    def post(self):
        """新增公告（任何登入者皆可）"""
        user = User.query.get(get_jwt_identity())
        if user is None:
            return {"status": "1", "result": "使用者不存在"}, 403
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

        announcement = Announcement(
            title=data["title"],
            content=data["content"],
            latitude=latitude,
            status=data.get["status"],
            longitude=longitude,
            created_by=user.id,
        )
        db.session.add(announcement)
        db.session.flush()  # 先儲存以獲得 announcement.id

        if photo_list := data.get("photo"): 
            filename = f"{announcement.id}_{announcement.title}"
            photos_path = save_photos(filename, photo_list, PHOTO_DIR)
            announcement.photo = json.dumps(photos_path)

        db.session.commit()
        return {"status": "0", "result": "公告已成功新增"}, 200

@api_ns.route("/announcements/<int:ann_id>")
class AnnouncementDetail(Resource):
    @jwt_required()
    @handle_request_exception
    def get(self, ann_id):
        """取得單一公告（with_photo=1 會帶照片）"""
        with_photo = request.args.get("with_photo") == "1"
        announcement = Announcement.query.get_or_404(ann_id)
        return {"status": "0", "result": announcement.to_dict(with_photo)}, 200

    @jwt_required()
    @handle_request_exception
    def put(self, ann_id):
        """編輯公告（只能編輯自己發布的或權限>1）"""
        user = User.query.get(get_jwt_identity())
        announcement = Announcement.query.get_or_404(ann_id)

        if announcement.created_by != user.id and user.permission <= 1:
            return {"status": "1", "result": "使用者權限不足"}, 403

        data = request.get_json()
        try:
            if coord := data.get("coordinates"):
                lat, lon = map(str.strip, coord.split(","))
                announcement.latitude = float(lat)
                announcement.longitude = float(lon)
        except Exception:
            raise BadRequest("經緯度輸入錯誤. 期望 'lat,lon'")

        for field in ("title", "content", "status"):
            if field in data:
                setattr(announcement, field, data[field])
        
        if "photo" in data:
            photo_value = data["photo"]
            if isinstance(photo_value, list):
                announcement.photo = json.dumps(photo_value)
            elif photo_value is None:
                announcement.photo = None
            else:
                raise BadRequest("photo 欄位必須是 list 或 None")

        announcement.updated_by = user.id
        db.session.commit()
        return {"status": "0", "result": "公告已成功編輯更新"}, 200

    @jwt_required()
    @handle_request_exception
    def delete(self, ann_id):
        """刪除公告（同上）"""
        user = User.query.get(get_jwt_identity())
        if user is None:
            return {"status": "1", "result": "使用者不存在"}, 403
        if user.permission <= 1:
            return {"status": "1", "result": "使用者權限不足"}, 403
        announcement = Announcement.query.get_or_404(ann_id)
        announcement.is_deleted = True
        announcement.updated_by = user.id
        # 如果有照片，則刪除照片檔案
        if announcement.photo:
            delete_photo_file(announcement.photo, PHOTO_DIR)
        db.session.commit()
        return {"status": "0", "result": "公告已經刪除"}, 200


@api_ns.route("/leaves")
class LeaveList(Resource):

    @jwt_required()
    @handle_request_exception
    def get(self):
        """取得請假列表  
        - 一般員工：只看自己的  
        - 主管 (permission>1)：看到全部
        """
        user = User.query.get(get_jwt_identity())
        query = Leave.query.filter(Leave.is_deleted == False)
        if user.permission <= 1:
            query = query.filter(Leave.user_id == user.id)
        leaves = query.order_by(Leave.created_at.desc()).all()
        return {
            "status": "0",
            "result": [l.to_dict() for l in leaves]
        }, 200
    
    @jwt_required()
    @handle_request_exception
    @api_ns.expect(leave_payload)
    def post(self):
        """使用者申請請假"""
        uid = get_jwt_identity()
        data = request.get_json()
        leave = Leave(
            user_id=uid,
            start_date=data["start_date"],
            end_date=data["end_date"],
            reason=data["reason"],
            status=0,
        )
        db.session.add(leave)
        db.session.commit()
        return {"status": "0", "result": "已提交請假申請"}, 200
    
@api_ns.route("/leaves/<int:leave_id>/approve")
class LeaveApprove(Resource):
    @jwt_required()
    @handle_request_exception
    def put(self, leave_id):
        """
        主管核准 / 駁回  
        JSON: {"action": "approve"} or {"action": "reject"}
        """
        user = User.query.get(get_jwt_identity())
        if user.permission <= 1:
            return {"status": "1", "result": "權限不足，無法准假"}, 403

        leave = Leave.query.get_or_404(leave_id)
        action = request.json.get("action")
        if action == "approve":
            leave.status = 1
        elif action == "reject":
            leave.status = 2
        else:
            return {"status": "1", "result": "管理者只能准假/駁回請假申請"}, 400

        leave.approver = user.id
        db.session.commit()
        return {"status": "0", "result": "已更新准假內容"}, 200
    
    @jwt_required()
    @handle_request_exception
    def delete(self, leave_id):
        """刪除公告（同上）"""
        user = User.query.get(get_jwt_identity())
        if user is None:
            return {"status": "1", "result": "使用者不存在"}, 403
        if user.permission <= 1:
            return {"status": "1", "result": "使用者權限不足"}, 403
        leave = Leave.query.get_or_404(leave_id)
        leave.is_deleted = True
        leave.updated_by = user.id
        db.session.commit()
        return {"status": "0", "result": "公告已經刪除"}, 200
        

@api_ns.route("/api/announcement-color", methods=["GET", "POST"])
class NoticeColorList(Resource):
    """
    GET  : 取得所有狀態與顏色 (dict)
    POST : 新增一筆狀態與顏色
    """

    @jwt_required()
    @handle_request_exception
    def get(self):
        rows = AnnocementColor.query.all()
        result: dict[str, str] = {}
        for r in rows:
            result.update(r.as_dict())
        return {"status": "0", "result": result}, 200

    @api.expect(announcemnt_color_model)
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
        if AnnocementColor.query.filter_by(status=status_name).first():
            return {"status": "1", "result": "有相同的狀態已經存在"}, 409

        nc = AnnocementColor(status=status_name, color=color)
        db.session.add(nc)
        db.session.commit()
        return {"status": "0", "result": f"已新增 {status_name} → {color}"}, 201


@api_ns.route("/sop")
class SOPVideoList(Resource):
    @jwt_required()
    @handle_request_exception
    def get(self):
        """前端只要拿 list 然後 <a href=video.youtube_url> 即可"""
        videos = SOPVideo.query.order_by(SOPVideo.date.desc()).all()
        return {"status": "0", "result": [v.to_dict() for v in videos]}, 200

    @jwt_required()
    @handle_request_exception
    # @api_ns.expect(sop_video_payload)
    def post(self):
        """新增影片（權限 >1 才能做）"""
        user = User.query.get(get_jwt_identity())
        if user.permission <= 1:
            return {"status": "1", "result": "使用者權限不足"}, 403
        data = request.get_json()
        vid = SOPVideo(
            date=data["date"],
            title=data["title"],
            youtube_url=data["youtube_url"],
            created_by=user.id,
        )
        db.session.add(vid)
        db.session.commit()
        return {"status": "0", "result": vid.to_dict()}, 201

@api_ns.route("/sop/<int:vid_id>")
class SOPVideoDetail(Resource):
    @jwt_required()
    @handle_request_exception
    def put(self, vid_id):
        user = User.query.get(get_jwt_identity())
        if user.permission <= 1:
            return {"status": "1", "result": "使用者權限不足"}, 403
        vid = SOPVideo.query.get_or_404(vid_id)
        data = request.get_json()
        for k in ("date", "title", "youtube_url"):
            if k in data:
                setattr(vid, k, data[k])
        vid.updated_by = user.id
        db.session.commit()
        return {"status": "0", "result": vid.to_dict()}, 200

    @jwt_required()
    @handle_request_exception
    def delete(self, vid_id):
        user = User.query.get(get_jwt_identity())
        if user.permission <= 1:
            return {"status": "1", "result": "使用者權限不足"}, 403
        vid = SOPVideo.query.get_or_404(vid_id)
        db.session.delete(vid)
        db.session.commit()
        return {"status": "0", "result": "deleted"}, 200