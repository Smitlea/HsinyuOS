import os
import json
import datetime
import pytz

from uuid import uuid4
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt

from util import encode_photo_to_base64


bcrypt = Bcrypt()
db = SQLAlchemy()
tz = pytz.timezone('Asia/Taipei')
 

class BaseTable(db.Model):
    __abstract__ = True
    __table_args__ = {"mysql_charset": "utf8mb4"}

    id           = db.Column(db.Integer, primary_key=True)
    recorded_at  = db.Column(db.TIMESTAMP, server_default=db.func.now(), nullable=False)
    created_at   = db.Column(db.DateTime(timezone=True), default=db.func.now())
    updated_at   = db.Column(db.DateTime(timezone=True), default=db.func.now(), onupdate=db.func.now())


class User(BaseTable):
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    permission = db.Column(db.Integer, default=0, nullable=False)

    def set_password(self, password):
        self.password = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password, password)

class Leave(BaseTable):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    start_date = db.Column(db.TIMESTAMP, nullable=False)
    end_date = db.Column(db.TIMESTAMP, nullable=False)
    reason = db.Column(db.String(150), nullable=False)
    status = db.Column(db.Integer, default=0, nullable=False)
    # approver = db.Column(db.String(150), default=0, nullable=False)
    # user = db.relationship('User', backref=db.backref('leaves', lazy=True))

class ConstructionSite(BaseTable):
    __tablename__ = "construction_site"

    id           = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    vendor       = db.Column(db.String(100), nullable=False)         # 廠商
    location     = db.Column(db.String(200), nullable=False)         
    photo        = db.Column(LONGTEXT, nullable=True)    
    latitude     = db.Column(db.Float(precision=53), nullable=False)   
    longitude    = db.Column(db.Float(precision=53), nullable=False)  
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
        }
        if include_photo and self.photo:
            try:
                paths = json.loads(self.photo)
                data["photo"] = [
                    f"data:image/jpeg;base64,{encode_photo_to_base64(p)}"
                    for p in paths if encode_photo_to_base64(p)
                ]
            except Exception as e:
                data["photo"] = []
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
    latitude     = db.Column(db.Float(precision=53), nullable=True)   
    longitude    = db.Column(db.Float(precision=53), nullable=True) 
    photo = db.Column(db.Text, nullable=True, comment="照片URL")
    site_id = db.Column(db.String(36), db.ForeignKey('construction_site.id'), nullable=False)
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
    crane = db.relationship("Crane", backref=db.backref("usages", cascade="all, delete-orphan"))

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
    photo = db.Column(LONGTEXT, nullable=True)  


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
    id         = db.Column(db.Integer, primary_key=True)
    crane_id   = db.Column(db.Integer, db.ForeignKey("cranes.id"))   
    site_id    = db.Column(db.String(36), db.ForeignKey("construction_site.id"))
    start_date = db.Column(db.Date, default=datetime.date.today)
    end_date   = db.Column(db.Date)  

    # optional：建立雙向關聯
    crane = db.relationship("Crane", backref=db.backref("assignments", cascade="all, delete-orphan"))
    site  = db.relationship("ConstructionSite", backref=db.backref("assignments", cascade="all, delete-orphan"))


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