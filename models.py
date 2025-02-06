import os
import datetime

from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt


bcrypt = Bcrypt()
db = SQLAlchemy()


class BaseTable(db.Model):
    __abstract__ = True
    __table_args__ = {"mysql_charset": "utf8mb4"}
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    timestamp = db.Column(db.TIMESTAMP, default=datetime.datetime.now, nullable=False)

class User(BaseTable):
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    permission = db.Column(db.Integer, default=0, nullable=False)

    def set_password(self, password):
        self.password = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password, password)
    
class Truck(BaseTable):
    name = db.Column(db.String(150), nullable=False)
    img = db.Column(db.String(150), nullable=True)
    model = db.Column(db.String(150), nullable=False)
    number = db.Column(db.String(150), nullable=False)
    track_lifespan = db.Column(db.Integer,default=0, nullable=False)
    crane_lifespan = db.Column(db.Integer,default=0, nullable=False)

class Leave(BaseTable):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    start_date = db.Column(db.TIMESTAMP, nullable=False)
    end_date = db.Column(db.TIMESTAMP, nullable=False)
    reason = db.Column(db.String(150), nullable=False)
    status = db.Column(db.Integer, default=0, nullable=False)
    approver = db.Column(db.String(150), default=0, nullable=False)
    # user = db.relationship('User', backref=db.backref('leaves', lazy=True))

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