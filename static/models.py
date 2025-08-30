import os
import json
import datetime
import time
from static.logger import get_logger
import pytz

from uuid import uuid4
from dotenv import load_dotenv
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import validates
from sqlalchemy.dialects.mysql import LONGTEXT
from flask_sqlalchemy import SQLAlchemy
from flask import g, request

from static.payload import app

from flask_bcrypt import Bcrypt
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity

from static.util import encode_photo_to_base64, photo_path_to_base64

logger = get_logger(__file__)

bcrypt = Bcrypt()
db = SQLAlchemy()
tz = pytz.timezone('Asia/Taipei')
 

class BaseTable(db.Model):
    __abstract__ = True
    __table_args__ = {"mysql_charset": "utf8mb4"}

    id           = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.datetime.now(tz))
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.datetime.now(tz), onupdate=datetime.datetime.now(tz))


class User(BaseTable):
    username = db.Column(db.String(150), unique=True, nullable=False)
    nickname = db.Column(db.String(150), unique=True, nullable=True)
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
    usages  = db.relationship("CraneUsage", back_populates="crane", uselist=False, cascade="all, delete-orphan")
    site = db.relationship("ConstructionSite",backref=db.backref("cranes", cascade="all, delete-orphan"))

    def __repr__(self):
        return f"<Crane {self.crane_number} ({self.crane_type})>"

# ------------ Crane ←→ CraneUsage ------------ #
class CraneUsage(BaseTable):
    """
    （一對一快取）每台吊車一筆的『累計使用小時』
    total_hours = crane.initial_hours + Σ DailyTask.work_time (is_deleted=False)
    ※ 只存快取，不再存每日+8h
    """
    __tablename__ = 'crane_usages'

    crane_id       = db.Column(db.Integer, db.ForeignKey('cranes.id'), nullable=False, unique=True)
    total_hours    = db.Column(db.Float, nullable=False, default=0.0)
    last_recalc_at = db.Column(db.DateTime(timezone=True), default=datetime.datetime.now(tz))

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
    updater = db.relationship(
        "User",
        foreign_keys=[updated_by],
        lazy="joined" 
    )

    site  = db.relationship("ConstructionSite", backref=db.backref("daily_tasks", cascade="all, delete-orphan"))
    crane = db.relationship("Crane",            backref=db.backref("daily_tasks", cascade="all, delete-orphan"))
    @property
    def updated_by_nickname(self) -> str | None:
        return self.updater.nickname if self.updater else None

class TaskMaintenance(BaseTable):
    """
    簡易保養紀錄 —— 僅描述字串 + 日期
    """
    __tablename__ = "task_maintenances"

    # user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    record_date  = db.Column(db.Date, default=datetime.date.today, nullable=False)
    description  = db.Column(db.Text, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    updated_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    creator = db.relationship(
        "User",
        foreign_keys=[created_by],
        lazy="joined" 
    )
    @property
    def nickname(self) -> str | None:
        return self.creator.nickname if self.creator else None


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
    site_id  = db.Column(db.String(36), db.ForeignKey("construction_site.id"))
    crane_id = db.Column(db.Integer,     db.ForeignKey("cranes.id"))
    note         = db.Column(db.String(150), nullable=True)  
    has_note    = db.Column(db.Boolean, default=False, nullable=False) 

    created_by  = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    updated_by   = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    is_deleted  = db.Column(db.Boolean, default=False, nullable=False)

    site  = db.relationship("ConstructionSite", backref=db.backref("work_records", cascade="all, delete-orphan"))
    crane = db.relationship("Crane",            backref=db.backref("work_records", cascade="all, delete-orphan"))

    updater = db.relationship(
        "User",
        foreign_keys=[updated_by],
        lazy="joined" 
    )

    @property
    def updated_by_nickname(self) -> str | None:
        return self.updater.nickname if self.updater else None
    
    @validates("note")
    def _auto_set_has_note(self, key, value):
        self.has_note = bool(value)
        return value

    def to_dict(self):
        return {
            "id": self.id,
            "crane": self.crane.crane_number,
            "site": self.site_id,
            "location": self.site.location,
            "record_date": self.record_date.isoformat(),
            "vendor": self.vendor,
            "note": self.note,
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
    has_location = db.Column(db.Boolean, default=False, nullable=False)
    record_date = db.Column(db.Date, default=datetime.date.today, nullable=False)
    photo = db.Column(LONGTEXT, nullable=True)  # 儲存圖片的 base64 字串
    latitude     = db.Column(db.Float(precision=53, asdecimal=False), nullable=True)   
    longitude    = db.Column(db.Float(precision=53, asdecimal=False), nullable=True) 
    status = db.Column(db.String(10), nullable=False, comment="注意事項狀態(聚會/注意)")
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    updated_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)

    @validates("photo")
    def _auto_set_has_photo(self, key, value):
        self.has_photo = bool(value)
        return value
    @validates("latitude")
    def _auto_set_has_location(self, key, value):
        self.has_location = bool(value)
        return value

    def to_dict(self, include_photo=False):
        data = {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "status": self.status,
            "record_date": self.record_date.isoformat(),
            "has_photo": self.has_photo,
            "has_location":self.has_location
        }
        if include_photo:
            data["latitude"] = self.latitude
            data["longitude"] = self.longitude
            if self.has_photo and self.photo:
                data["photo"] = photo_path_to_base64(self.photo)
            
        return data


class AnnocementColor(BaseTable):
    __tablename__ = "annocementcolor"
    
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(50), unique=True, nullable=False)
    color = db.Column(db.String(20), nullable=False)

    def as_dict(self) -> dict[str, str]:
        """回傳 {status: color} 的單筆 dict 方便外層組裝"""
        return {self.status: self.color}


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



def _sum_usage_hours(crane_id: int) -> float | None:
    """
    總時數 = initial_hours + Σ DailyTask.work_time（is_deleted=False）
    同步寫回一對一的 CraneUsage（快取）
    """
    crane = Crane.query.get(crane_id)
    if not crane:
        return None

    total_work = db.session.query(
        func.coalesce(func.sum(DailyTask.work_time), 0.0)
    ).filter(
        DailyTask.crane_id == crane_id,
        DailyTask.is_deleted.is_(False)
    ).scalar() or 0.0

    base  = float(crane.initial_hours or 0.0)
    total = base + float(total_work)

    if crane.usages is None:
        crane.usages = CraneUsage(crane_id=crane_id, total_hours=total)
    else:
        crane.usages.total_hours = total
        crane.usages.last_recalc_at = datetime.datetime.now(tz)

    db.session.commit()
    return total

def _pending_parts_in_current_cycle(crane_id: int, total_hours: int | None = None):
    """
    回傳 (info, due_parts, pending_parts)
    - info: _cycle_info(...) 的結果
    - due_parts: 本週期理應要更換的零件（代碼清單）
    - pending_parts: 該週期尚未更換的零件（代碼清單）
    """
    crane = Crane.query.get(crane_id)
    if not crane:
        return None, [], []

    # 若沒給 total_hours，幫忙算；這也會同步快取到 CraneUsage
    if total_hours is None:
        total_hours = _sum_usage_hours(crane_id)
        if total_hours is None:
            return None, [], []

    info = _cycle_info(int(total_hours))
    due_parts = _due_parts_for_cycle(info["cycle_index"])

    # 此吊車該週期內已經更換過的零件
    records = (
        MaintenanceRecord.query
        .filter(
            MaintenanceRecord.crane_id == crane_id,
            MaintenanceRecord.maintenance_hours >= info["cycle_start"],
            MaintenanceRecord.maintenance_hours <  info["cycle_end"],
        ).all()
    )
    already = set()
    for r in records:
        if r.parts:
            already.update(r.parts)

    pending = [p for p in due_parts if p not in already]
    return info, sorted(due_parts), sorted(pending)

# ────────── 常數（與你原本一致） ──────────
CYCLE_HOURS = 500
CYCLES_PER_ROUND = 12
ROUND_HOURS = CYCLE_HOURS * CYCLES_PER_ROUND  # 6000

# 需要紀錄的濾心（代碼）
CONSUMABLES_HINTS = {
    "engine_oil": ["engine_oil_filter", "fuel_oil_filter"],
    "circulation_oil": ["braker_drain_filter", "circulation_drain_filter", "circulation_inlet_filter", "circulation_return_filter"],
}


def _cycle_info(total_hours: int) -> dict:
    """
    傳回目前所在週期資訊：
    - cycle_index: 1~12
    - round_base: 本輪起始基準小時（例如 12000、18000…）
    - cycle_start, cycle_end: 本週期的小時範圍 [start, end)
    """
    # 本輪偏移
    offset = total_hours % ROUND_HOURS  # 0~5000
    cycle_index = (offset // CYCLE_HOURS) + 1  # 1..12
    round_base = total_hours - offset          # 0, 5000, 10000, ...
    cycle_start = round_base + (cycle_index - 1) * CYCLE_HOURS
    cycle_end = cycle_start + CYCLE_HOURS
    return {
        "cycle_index": int(cycle_index),
        "round_base": int(round_base),
        "cycle_start": int(cycle_start),
        "cycle_end": int(cycle_end),
    }

def _due_parts_for_cycle(cycle_index: int) -> list[str]:
    """
    規則：
    - 機油：每 500h（每一週期）
    - 主捲、獅頭齒輪油：每 1000h（週期 2,4,6,8,10,12）
    - 補捲、起伏、旋回齒輪油：每 1500h（週期 3,6,9,12）
    - 循環油：每 2000h（週期 4,8,12）
    - 皮帶、齒盤：每 6000h（週期 12），加「齒盤上油」
    """
    due = {"engine_oil"}  # 每期都要
    if cycle_index % 2 == 0:
        due.update({"main_hoist_gear_oil", "lion_head_gear_oil"})
    if cycle_index % 3 == 0:
        due.update({"aux_hoist_gear_oil", "luffing_gear_oil", "slewing_gear_oil"})
    if cycle_index % 4 == 0:
        due.add("circulation_oil")
    if cycle_index == 12:
        due.update({"belts", "sprocket", "sprocket_oiling"})
    return sorted(due)

# ────────── 保養紀錄模型 ──────────
class MaintenanceRecord(BaseTable):
    """
    正式保養紀錄（多選零件 + 可記錄濾心耗材）
    """
    __tablename__ = "maintenance_records"

    crane_id = db.Column(db.Integer, db.ForeignKey("cranes.id"), nullable=False)
    record_date = db.Column(db.Date, nullable=False, default=datetime.date.today)
    maintenance_hours = db.Column(db.Integer, nullable=False, comment="保養時的整點小時數")
    parts = db.Column(db.JSON, nullable=False, default=list, comment="本次更換的零件代碼陣列")
    consumables = db.Column(db.JSON, nullable=True, comment="本次更換的濾心耗材代碼陣列")
    note = db.Column(db.String(150), nullable=True)

    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

    crane = db.relationship("Crane", backref=db.backref("maintenance_records", cascade="all, delete-orphan"))

    def to_dict(self):
        return {
            "id": self.id,
            "crane_id": self.crane_id,
            "record_date": self.record_date.isoformat(),
            "maintenance_hours": self.maintenance_hours,
            "parts": self.parts,
            "consumables": self.consumables or [],
            "note": self.note,
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