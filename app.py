import os
import random
import string
from datetime import timedelta

from dotenv import load_dotenv
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity, create_refresh_token
)
from sqlalchemy import inspect      
from payload import (
    api_ns, api, app,
    refresh_input_payload,
    login_output_payload,
    general_output_payload,
    register_payload,
    forgot_password_payload,
    login_payload
)
from flask_bcrypt import Bcrypt
from flask_restx import Resource

from vehicle import *
from location import *
from models import db, User
from logger import logging
from util import handle_request_exception

bcrypt = Bcrypt()
logger = logging.getLogger(__file__)
jwt = JWTManager(app)

load_dotenv(override=True)


# ─────────────────────────────────────────────────────────────
# Flask 設定
# ─────────────────────────────────────────────────────────────
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("SQL_SERVER")
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY')
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(minutes=60)
app.config["JWT_REFRESH_TOKEN_EXPIRES"] = timedelta(days=1) 
app.config["PROPAGATE_EXCEPTIONS"] = True
app.config['API_KEY']= os.environ.get('API_SECRET_KEY')
app.config['CACHE_TYPE'] = 'RedisCache'
app.config['CACHE_REDIS_URL'] = os.getenv('REDIS_URL')

# ─────────────────────────────────────────────────────────────
# 初始建表＋預設資料
# ─────────────────────────────────────────────────────────────
DEFAULT_NOTICE_COLORS = {
    "待修": "#ff0000",   # 紅
    "異常": "#00ff00",   # 綠
    "現場": "#0000ff",   # 藍
}

def _init_notice_color():
    """如果 notice_color 表不存在就創建並塞預設三筆。"""
    inspector = inspect(db.engine)
    if NoticeColor.__tablename__ not in inspector.get_table_names():
        logger.info("Creating notice_color table ...")
        NoticeColor.__table__.create(bind=db.engine)

    # 檢查並插入預設資料
    for status, color in DEFAULT_NOTICE_COLORS.items():
        if not NoticeColor.query.filter_by(status=status).first():
            db.session.add(NoticeColor(status=status, color=color))
            logger.info(f"Insert default NoticeColor: {status} → {color}")
    db.session.commit()

db.init_app(app)
with app.app_context():
    db.create_all()
    _init_notice_color() 
    logger.info('DB init done')



@api_ns.route('/api/register', methods=['POST'])
class Register(Resource):
    @handle_request_exception
    @api.expect(register_payload)
    @api.marshal_with(general_output_payload)
    def post(self):
        """
        註冊
        """
        data = api.payload
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')
        try:
            if User.query.filter_by(username=username).first():
                return ({'status':1, 'result': '這個用戶已存在'}), 200
            new_user = User(username=username, email=email)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            
            logger.info(f'Register user:{username} id:{new_user.id}')
            return {'status':0, 'result': '註冊成功'}
        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0]
            logger.warning(f"Register Error: [{error_class}] detail: {detail}")
            return {'status':1, 'result': error_class, 'error': detail}, 500

@api_ns.route('/api/login', methods=['POST'])
class login(Resource):
    @handle_request_exception
    @api.expect(login_payload)
    @api.marshal_with(login_output_payload)
    def post(self):
        """
        登入
        """
        try:
            data = api.payload
            username = data.get('username')
            password = data.get('password')

            user = User.query.filter_by(username=username).first()
            if user and user.check_password(password):
                access_token = create_access_token(identity=str(user.id), expires_delta=timedelta(minutes=60))
                refresh_token = create_refresh_token(identity=username)

                return ({'status':0, 'result': access_token, 'refresh_token': refresh_token})

            return {'status':1, 'result': '密碼或使用者名稱不相符'}
        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0]
            logger.warning(f"login Error: [{error_class}] detail: {detail}")
            return {'status':1, 'result': str(e)}

@api_ns.route('/api/forgot', methods=['POST'])
class ForgotPassword(Resource):
    @handle_request_exception
    @api.expect(forgot_password_payload)
    @api.marshal_with(general_output_payload)
    def post(self):
        """
        忘記密碼
        """
        try:
            data = api.payload
            email = data.get('email')

            user = User.query.filter_by(email=email).first()
            if user:
                random_password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
                hashed_password = bcrypt.generate_password_hash(random_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                db.session.query(User).filter_by(email=email).update({'password': hashed_password})
                db.session.commit()
                return {'status': 0, 'result': '密碼以寄送至信箱'}

            return {'status': 1, 'result': 'User not found'}

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0]
            logger.warning(f"Forgot PW Error: [{error_class}] detail: {detail}")
            return {'status': 1, 'result': str(e), "error": detail}


@api_ns.route('/api/test', methods=['GET'])
class Test(Resource):
    @handle_request_exception
    def get(self):
        return {'status': 0, 'result': "you are connect Houston"}

@api_ns.route('/api/auth', methods=['GET'])
class Auth(Resource):
    @api.doc(params={'jwt': ''})
    @jwt_required()
    @handle_request_exception
    def get(self):
        user = User.query.get(get_jwt_identity())
        if not user:
            return {'status': 1, 'result': '使用者不存在'}
        return {'status': 0, 'result': user.username}
    
@api_ns.route('/api/check_permission', methods=['GET'])
class Check(Resource):
    @api.doc(params={'jwt': ''})
    @jwt_required()
    @handle_request_exception
    def get(self):
        user = db.session.get(User, get_jwt_identity())
        if not user:
            return {'status': 1, 'result': '使用者不存在'}
        return {'status': 0, 'result': user.permission}
    

@api_ns.route("/api/refresh", methods=["POST"])
class Refresh(Resource):
    @jwt_required(refresh=True)
    @handle_request_exception
    @api.expect(refresh_input_payload)
    @api.marshal_with(login_output_payload)
    def post(self):
        try:
            current_user = get_jwt_identity()
            print(f"current_user: {current_user}")
            user = User.query.filter_by(username=current_user).first()
            if not user:
                return {'status': 1, 'result': '使用者不存在'}
            new_access_token = create_access_token(identity=str(user.id), expires_delta=timedelta(minutes=60))
            new_refresh_token = create_refresh_token(identity=current_user)
            return {'status': 0, 'result': new_access_token, 'refresh_token': new_refresh_token}
        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0]
            logger.warning(f"login Error: [{error_class}] detail: {detail}")
            return {'status':1, 'result': str(e)}


# 補充 JWT 錯誤處理
@jwt.expired_token_loader
def handle_expired_token(jwt_header, jwt_payload):
    return {
        "status": 1,
        "result": "Token 已過期，請重新登入",
        "error": "InvalidSignatureError: Signature verification failed"
    }, 401

@jwt.invalid_token_loader
def handle_no_auth_header(reason):
    return {
            "status": 1,
            "result": "請提供有效的授權憑證（Authorization Header）",
            "error":"InvalidSignatureError:  Signature verification failed" 
    }, 401

@jwt.unauthorized_loader
def handle_unauthorized(reason):
    return {
        "status": 1, 
        "result": "未授權的請求，請提供有效的 Token",
        "error": "Unauthorized: No Authorization header provided"
    }, 401

@jwt.revoked_token_loader
def handle_invalid_token(jwt_header, jwt_payload):
    return {
        "status": 1,
        "result": "無效或已撤銷的 Token",
        "error": "Token has been revoked"
    }, 401

   
# @api_ns.route("/users")
# def user_list():
#     users = db.session.execute(db.select(User).order_by(User.username)).scalars()

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=False)
