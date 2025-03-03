import os
import datetime
import pytz

from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt


bcrypt = Bcrypt()
db = SQLAlchemy()
tz = pytz.timezone('Asia/Taipei')

class BaseTable(db.Model):
    __abstract__ = True
    __table_args__ = {"mysql_charset": "utf8mb4"}
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    timestamp = db.Column(db.TIMESTAMP, default=datetime.datetime.now(tz), nullable=False)

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

class Crane(BaseTable):
    """
    吊車基本資料
    - 履帶：滿 500 小時顯示警示
    - 輪式：滿 1000 小時顯示警示
    - initial_hours：初始為 100 小時
    """
    __tablename__ = 'cranes'
    crane_number = db.Column(db.String(50), unique=True, nullable=False, comment="車號")
    crane_type = db.Column(db.String(20), nullable=False, comment="吊車種類(履帶/輪式)")
    initial_hours = db.Column(db.Integer, nullable=False, default=100, comment="初始小時數，預設100")
    # 您也可以依需求將累計使用小時放在同一張表內再搭配計算，這裡留給 daily usage 紀錄彈性
    location = db.Column(db.String(255), nullable=True, comment="地理位置描述")
    photo_url = db.Column(db.String(255), nullable=True, comment="照片URL(或檔名)")
    created_at = db.Column(db.DateTime, default=datetime.datetime.now(tz), comment="建立時間")

    def __repr__(self):
        return f"<Crane {self.crane_number} ({self.crane_type})>"


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

    crane = db.relationship("Crane", backref=db.backref("notices", cascade="all, delete-orphan"))

    def __repr__(self):
        return f"<CraneNotice crane_id={self.crane_id}, date={self.notice_date}, status={self.status}>"


class CraneMaintenance(BaseTable):
    """
    維修圖(維修相關資訊)，三個可自由填寫的欄位
    """
    __tablename__ = 'crane_maintenances'
    crane_id = db.Column(db.Integer, db.ForeignKey('cranes.id'), nullable=False)
    maintenance_date = db.Column(db.Date, default=datetime.datetime.now(tz), comment="維修日期")

    # 三個欄位可做彈性運用，例如記錄維修部位、維修內容、負責人等
    field1 = db.Column(db.String(255), nullable=True, comment="自訂欄位1")
    field2 = db.Column(db.String(255), nullable=True, comment="自訂欄位2")
    field3 = db.Column(db.String(255), nullable=True, comment="自訂欄位3")

    crane = db.relationship("Crane", backref=db.backref("maintenances", cascade="all, delete-orphan"))

    def __repr__(self):
        return f"<CraneMaintenance crane_id={self.crane_id}, date={self.maintenance_date}>"


if __name__ == '__main__':
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