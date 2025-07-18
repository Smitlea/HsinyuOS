import os
import json
import datetime
import time
from static.logger import get_logger
import pytz

from uuid import uuid4
from dotenv import load_dotenv
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import validates
from sqlalchemy.dialects.mysql import LONGTEXT
from flask_sqlalchemy import SQLAlchemy
from flask import g, request

from static.payload import app

from flask_bcrypt import Bcrypt
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity

from static.util import encode_photo_to_base64

logger = get_logger(__file__)

bcrypt = Bcrypt()
db = SQLAlchemy()
tz = pytz.timezone('Asia/Taipei')
 
def UTC8():
    return datetime.datetime.now(tz)

class BaseTable(db.Model):
    __abstract__ = True
    __table_args__ = {"mysql_charset": "utf8mb4"}

    id           = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), default=UTC8)
    updated_at = db.Column(db.DateTime(timezone=True), default=UTC8, onupdate=UTC8)


class User(BaseTable):
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    permission = db.Column(db.Integer, default=0, nullable=False)

    def set_password(self, password):
        self.password = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password, password)
class UserProfile(BaseTable):
    __tablename__ = "user_profile"

    # user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    # user = db.relationship('User', backref=db.backref('profile', uselist=False))
    
    def to_dict(self):
        return {"name": self.phone}
    

class ConstructionSite(BaseTable):
    __tablename__ = "construction_site"

    id           = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    vendor       = db.Column(db.String(100), nullable=False)         # 廠商
    location     = db.Column(db.String(200), nullable=False)         
    photo        = db.Column(LONGTEXT, nullable=True)    
    latitude     = db.Column(db.Float(precision=53, asdecimal=False), nullable=False)   
    longitude    = db.Column(db.Float(precision=53, asdecimal=False), nullable=False)  
    note         = db.Column(db.String(100), nullable=True)  
    is_deleted   = db.Column(db.Boolean, default=False, nullable=False)
    created_by   = db.Column(db.Integer, db.ForeignKey("user.id"))   


    creator = db.relationship("User", backref="sites")
    def to_dict(self, include_photo: bool = True):
        data = {
            "id": self.id,
            "vendor": self.vendor,
            "note": self.note,
            "location": self.location,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "created_at": self.created_at,
            "has_photo": False
        }
        paths = json.loads(self.photo) if self.photo else []
        if not isinstance(paths, list):
            raise ValueError("photo 欄位不是 list 格式")

        data["has_photo"] = bool(paths)

        if include_photo and data["has_photo"]:
            data["photo"] = [
                f"data:image/jpeg;base64,{encode_photo_to_base64(p)}"
                for p in paths if encode_photo_to_base64(p)
            ]

        return data


# ------------ Crane ←→ ConstructionSite ------------ #
class Crane(BaseTable):
    """
    吊車基本資料
    - 履帶：滿 500 小時顯示警示
    - 輪式：滿 1000 小時顯示警示
    - initial_hours：初始為 100 小時
    """
    __tablename__ = 'cranes'
    crane_number = db.Column(db.String(50), unique=True, nullable=False, comment="車號")
    crane_type = db.Column(db.Boolean, comment="吊車類型：1=履帶式，0=輪式", nullable=False)
    initial_hours = db.Column(db.Integer, nullable=False, default=100, comment="初始小時數，預設100")
    latitude     = db.Column(db.Float(precision=53, asdecimal=False), nullable=True)   
    longitude    = db.Column(db.Float(precision=53, asdecimal=False), nullable=True) 
    photo = db.Column(db.Text, nullable=True, comment="照片URL")
    site_id = db.Column(db.String(36), db.ForeignKey('construction_site.id'), nullable=False)
    usages = db.relationship("CraneUsage", back_populates="crane", lazy="selectin")
    site = db.relationship("ConstructionSite",backref=db.backref("cranes", cascade="all, delete-orphan"))

    def __repr__(self):
        return f"<Crane {self.crane_number} ({self.crane_type})>"

# ------------ Crane ←→ CraneUsage ------------ #
class CraneUsage(BaseTable):
    """
    每日使用小時紀錄：每個 crane_id 一天一筆或多筆的使用紀錄
    - 預設每一天 +8 小時，可自由調整
    """
    __tablename__ = 'crane_usages'
    crane_id = db.Column(db.Integer, db.ForeignKey('cranes.id'), nullable=False)
    usage_date = db.Column(db.Date, nullable=False, comment="使用日期")
    daily_hours = db.Column(db.Integer, nullable=False, default=8, comment="當日使用小時(預設8)")


    # 多對一關係：一台吊車對多筆使用紀錄
    crane = db.relationship("Crane", back_populates="usages")
    def __repr__(self):
        return f"<CraneUsage crane_id={self.crane_id}, date={self.usage_date}, hours={self.daily_hours}>"

# ------------ Crane ←→ CraneNotice ------------ #
class CraneNotice(BaseTable):
    """
    注意事項：
    - 狀態：待修 / 異常 / 現場
    - 日期、注意大綱、詳細事項
    """
    __tablename__ = 'crane_notices'
    crane_id = db.Column(db.Integer, db.ForeignKey('cranes.id'), nullable=False)
    notice_date = db.Column(db.Date, default=datetime.datetime.now(tz), comment="注意事項日期")
    status = db.Column(db.String(10), nullable=False, comment="注意事項狀態(待修/異常/現場)")
    title = db.Column(db.String(100), nullable=False, comment="注意事項大綱")
    description = db.Column(db.Text, nullable=True, comment="注意事項的詳細描述")
    is_deleted = db.Column(db.Boolean, default=False, nullable=False, comment="是否已刪除")
    photo = db.Column(LONGTEXT, nullable=True, comment="照片URL")  
    created_by   = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False) 
    updated_by  = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)


    crane = db.relationship("Crane", backref=db.backref("notices", cascade="all, delete-orphan"))

    def __repr__(self):
        return f"<CraneNotice crane_id={self.crane_id}, date={self.notice_date}, status={self.status}>"

class NoticeColor(BaseTable):
    __tablename__ = "notice_color"
    
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(50), unique=True, nullable=False)
    color = db.Column(db.String(20), nullable=False)

    def as_dict(self) -> dict[str, str]:
        """回傳 {status: color} 的單筆 dict 方便外層組裝"""
        return {self.status: self.color}

# ------------ Crane ←→ CraneMaintenance ------------ #
class CraneMaintenance(BaseTable):
    """
    維修圖(維修相關資訊)，三個可自由填寫的欄位
    """
    __tablename__ = 'crane_maintenances'
    crane_id = db.Column(db.Integer, db.ForeignKey('cranes.id'), nullable=False)
    maintenance_date = db.Column(db.Date, default=datetime.datetime.now(tz), comment="維修日期")

    # 三個欄位可做彈性運用，例如記錄維修部位、維修內容、負責人等
    title    = db.Column(db.String(128), nullable=False)      # 標題
    note     = db.Column(db.Text,        nullable=True)       # 備註
    material = db.Column(db.String(128), nullable=True)       # 使用材料
    photo = db.Column(LONGTEXT, nullable=True)  

    vendor         = db.Column(db.String(128))
    vendor_cost    = db.Column(db.Numeric(12, 2))
    parts_vendor   = db.Column(db.String(128))
    parts_cost     = db.Column(db.Numeric(12, 2))
    created_by   = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False) 
    is_deleted   = db.Column(db.Boolean, default=False, nullable=False)


    crane = db.relationship("Crane", backref=db.backref("maintenances", cascade="all, delete-orphan"))

    def __repr__(self):
        return f"<CraneMaintenance crane_id={self.crane_id}, date={self.maintenance_date}>"

# ------------ Crane / ConstructionSite ←→ CraneAssignment ------------ #
class CraneAssignment(BaseTable):
    __tablename__ = "crane_assignments"          
    crane_id   = db.Column(db.Integer, db.ForeignKey("cranes.id"))   
    site_id    = db.Column(db.String(36), db.ForeignKey("construction_site.id"))
    start_date = db.Column(db.Date, default=datetime.date.today)
    end_date   = db.Column(db.Date)  

    # optional：建立雙向關聯
    crane = db.relationship("Crane", backref=db.backref("assignments", cascade="all, delete-orphan"))
    site  = db.relationship("ConstructionSite", backref=db.backref("assignments", cascade="all, delete-orphan"))

    __table_args__ = (
        # 同一台吊車派同一天不得重疊（簡化版；如需跨區間完整重疊檢查靠程式驗證）
        db.Index("uq_crane_date", "crane_id", "start_date", unique=False),
    )
    def covers(self, target_date: datetime.date) -> bool:
        return (self.start_date <= target_date and
                (self.end_date is None or self.end_date >= target_date))
    
class DailyTask(BaseTable):
    """
    每日任務紀錄
    ─ vendor      : 廠商名稱
    ─ site_id     : 對應 ConstructionSite.id
    ─ crane_id    : 對應 Crane.id（車號）
    ─ work_time   : 工作時間字串（ex: "7.5"
    ─ note        : 備註
    """
    __tablename__ = "daily_tasks"

    task_date  = db.Column(db.Date, default=datetime.date.today, nullable=False)
    vendor     = db.Column(db.String(100), nullable=False)
    work_time  = db.Column(db.Float,  nullable=False)
    note       = db.Column(db.Text,        nullable=True)

    site_id  = db.Column(db.String(36), db.ForeignKey("construction_site.id"))
    crane_id = db.Column(db.Integer,     db.ForeignKey("cranes.id"))
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    updated_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)

    site  = db.relationship("ConstructionSite", backref=db.backref("daily_tasks", cascade="all, delete-orphan"))
    crane = db.relationship("Crane",            backref=db.backref("daily_tasks", cascade="all, delete-orphan"))

class TaskMaintenance(BaseTable):
    """
    簡易保養紀錄 —— 僅描述字串 + 日期
    """
    __tablename__ = "task_maintenances"

    maintenance_date   = db.Column(db.Date, default=datetime.date.today, nullable=False)
    description        = db.Column(db.Text, nullable=False)

class WorkRecord(BaseTable):
    """
    怪手工作紀錄（第二項）
    ─ vendor        : 廠商（字串）
    ─ qty_120 / 200 : 出勤台數（整數，可為 0）
    ─ assistants    : 4 人以內的 user.id 陣列，JSON 儲存
    """
    __tablename__ = "work_records"

    record_date = db.Column(db.Date, default=datetime.date.today, nullable=False)
    vendor      = db.Column(db.String(100), nullable=False)
    qty_120     = db.Column(db.Integer, default=0, nullable=False)
    qty_200     = db.Column(db.Integer, default=0, nullable=False)
    assistants   = db.Column(db.JSON) 

    created_by  = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    update_by   = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    is_deleted  = db.Column(db.Boolean, default=False, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "record_date": self.record_date.isoformat(),
            "vendor": self.vendor,
            "qty_120": self.qty_120,
            "qty_200": self.qty_200,
            "assistants": self.assistants if self.assistants else [],
        }
    
# ------------- Truck --------------- #
class Truck(BaseTable):
    """
    貨車基本資料（僅追蹤車號、GPS，可再加容量、車型…）
    """
    __tablename__ = "trucks"

    truck_number = db.Column(db.String(50), unique=True, nullable=False, comment="車號")

    def drum_remain(self) -> float:
        """目前油桶殘量（IN – OUT）"""
        ins  = sum(r.quantity for r in self.drum_records
               if not r.is_deleted and r.io_type == "IN")
        outs = sum(r.quantity for r in self.drum_records
               if not r.is_deleted and r.io_type == "OUT")
        return round(ins - outs, 2)

    def fuel_remain(self) -> float:
        """
        貨車油箱殘量（目前以『加進去的量累加』方式估算）
        若之後要扣除行駛耗油，可另外建 consumption 類型
        """
        return round(sum(r.quantity for r in self.fuel_records if not r.is_deleted), 2)
    
# ------------- 油桶紀錄 --------------- #
# ── 油桶紀錄（IN / OUT） ───────────────────────
class OilDrumRecord(BaseTable):
    """
    油桶 IN / OUT 紀錄
    ─ io_type  : IN 表補桶、OUT 表出油到機械
    ─ quantity : 正數（L）
    ─ unit_price: IN 時必填，Numeric(7,1) => 0~99999.9
    """
    __tablename__ = "oil_drum_records"
    truck_id    = db.Column(db.Integer, db.ForeignKey("trucks.id"), nullable=False)
    record_date = db.Column(db.Date, default=datetime.date.today, nullable=False)
    io_type     = db.Column(db.Enum("IN", "OUT", name="drum_io_type"), nullable=False)
    quantity    = db.Column(db.Numeric(10,2), nullable=False)
    unit_price  = db.Column(db.Numeric(7,1), nullable=True)
    updated_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    crane_number = db.Column(db.String(50), db.ForeignKey("cranes.crane_number"), nullable=True)

    truck = db.relationship("Truck", backref=db.backref("drum_records", cascade="all, delete-orphan"))
    crane = db.relationship("Crane", backref=db.backref("drum_refuels", lazy="dynamic"))
    __table_args__ = (db.CheckConstraint("quantity >= 0", name="chk_drum_qty_nonneg"),)

class TruckFuelRecord(BaseTable):
    """
    貨車本身加油紀錄（車隊油箱）
    ─ quantity  : 加油量 (L) 必為正
    ─ unit_price: 單價 (1 位小數，元/L)
    """
    __tablename__ = "truck_fuel_records"
    truck_id    = db.Column(db.Integer, db.ForeignKey("trucks.id"), nullable=False)
    record_date = db.Column(db.Date, default=datetime.date.today, nullable=False)
    quantity    = db.Column(db.Numeric(10,2), nullable=False)
    unit_price  = db.Column(db.Numeric(7,1), nullable=False)
    updated_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)

    truck = db.relationship("Truck", backref=db.backref("fuel_records", cascade="all, delete-orphan"))

    __table_args__ = (
        db.CheckConstraint("quantity >= 0", name="chk_fuel_qty_nonneg"),
    )
    
@app.before_request
def start_timer():
    g.start_time = time.time()

@app.before_request
def load_logged_in_user():
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        if identity:
            user = User.query.get(identity)
            g.user = user
        else:
            g.user = None
    except Exception:
        g.user = None

@app.after_request
def log_response_time(response):
    if hasattr(g, 'start_time'):
        elapsed = time.time() - g.start_time
        logger.debug(f"[{request.method}] {request.path} took {elapsed:.3f} seconds")
    return response

#------------ Announcement --------------- #
class Announcement(BaseTable):
    __tablename__ = "announcements"
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    has_photo = db.Column(db.Boolean, default=False, nullable=False)
    record_date = db.Column(db.Date, default=datetime.date.today, nullable=False)
    photo = db.Column(LONGTEXT, nullable=True)  # 儲存圖片的 base64 字串
    latitude     = db.Column(db.Float(precision=53, asdecimal=False), nullable=True)   
    longitude    = db.Column(db.Float(precision=53, asdecimal=False), nullable=True) 
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    updated_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)

    @validates("photo")
    def _auto_set_has_photo(self, key, value):
        self.has_photo = bool(value)
        return value

    def to_dict(self, with_photo=False):
        data = {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "record_date": self.record_date.isoformat(),
            "has_photo": self.has_photo
        }
        if with_photo and self.has_photo and self.photo:
            data["photo"] = f"data:image/jpeg;base64,{self.photo}"
        return data
    
class Leave(BaseTable):
    __tablename__ = "leaves"

    user_id    = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    start_date = db.Column(db.TIMESTAMP, nullable=False)
    end_date   = db.Column(db.TIMESTAMP, nullable=False)
    reason     = db.Column(db.String(150), nullable=False)
    status     = db.Column(db.Integer, default=0, nullable=False)  # 0=pending,1=approved,2=rejected
    approver   = db.Column(db.Integer, db.ForeignKey("user.id"))
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "reason": self.reason,
            "status": self.status,
            "approver": self.approver,
            "created_at": self.created_at.isoformat(),
        }
    

class SOPVideo(BaseTable):
    __tablename__ = "sop_videos"

    date         = db.Column(db.Date, nullable=False)
    title        = db.Column(db.String(150), nullable=False)
    youtube_url  = db.Column(db.String(255), nullable=False)
    is_deleted    = db.Column(db.Boolean, default=False, nullable=False)
    created_by   = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    updated_by   = db.Column(db.Integer, db.ForeignKey("user.id"))

    def to_dict(self):
        return {
            "id": self.id,
            "date": self.date.isoformat(),
            "title": self.title,
            "youtube_url": self.youtube_url,
        }

if __name__ == "__main__":
    dotenv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")

    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path)

    db.drop_all()
    db.create_all()





# if __name__ == "__main__":
#     dotenv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
#     print(dotenv_path)
#     if os.path.exists(dotenv_path):
#         load_dotenv(dotenv_path)

#     engine = create_engine(os.environ.get("SQL_SERVER"), echo=True)
#     Base.metadata.drop_all(engine)
#     Base.metadata.create_all(engine)