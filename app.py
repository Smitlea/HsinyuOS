import os
import secrets
import string

from dotenv import load_dotenv
from flask import request
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity
)
from payload import (
    api_ns, api, app, api_test,
    general_output_payload,
    register_payload,
    forgot_password_payload,
    login_payload
)
from flask_bcrypt import Bcrypt
from flask_restx import Resource
from models import db, User, Truck
from logger import logging
from util import handle_request_exception

bcrypt = Bcrypt()
logger = logging.getLogger(__file__)
jwt = JWTManager(app)
load_dotenv()

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("SQL_SERVER")  # 環境變數中的資料庫 URL
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False  # 關閉事件追蹤，提升性能

db.init_app(app)
with app.app_context():
    db.create_all()
    logger.info('DB init done')


# class AuthorizationManager():
#     def __init__(self):
#         self.permission = 0

#     def check_permission(self, user_id):
#         user = User.query.get(user_id)
#         if user:
#             self.permission = user.permission
#         return self.permission

@api_ns.route('/api/register', methods=['POST'])
class Register(Resource):
    @handle_request_exception
    @api.expect(register_payload)
    @api.marshal_with(general_output_payload)
    def post(self):
        data = api.payload
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')
        try:
            if User.query.filter_by(username=username).first():
                return ({'status':1, 'result': 'Username already exists'}), 400
            # if User.query.filter_by(email=email).first():
            #     return ({'status':'1','result': 'Email already exists'}), 400
            new_user = User(username=username, email=email)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            
            logger.info(f'Register user:{username} id:{new_user.id}')
            return {'status':0, 'result': '註冊成功}'}
        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0]
            logger.warning(f"Register Error: [{error_class}] detail: {detail}")
            return {'status':1, 'result': error_class, 'error': detail}

@api_ns.route('/api/login', methods=['POST'])
class login(Resource):
    @handle_request_exception
    @api.expect(login_payload)
    @api.marshal_with(general_output_payload)
    def post(self):
        try:
            data = api.payload
            username = data.get('username')
            password = data.get('password')

            user = User.query.filter_by(username=username).first()
            if user and user.check_password(password):
                access_token = create_access_token(identity=user.id)
                return ({'status':0, 'result': access_token}), 200

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
        用戶忘記密碼的處理邏輯
        """
        try:
            data = api.payload
            email = data.get('email')

            user = User.query.filter_by(email=email).first()
            if user:
                characters = string.ascii_letters + string.digits + string.punctuation
                random_password = ''.join(secrets.choice(characters) for _ in range(12))
                hashed_password = bcrypt.hashpw(random_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                db.session.query(User).filter_by(email=email).update({'password': hashed_password})
                db.session.commit()
                return {'status': 0, 'result': '密碼以寄送至信箱'}

            return {'status': 1, 'result': 'User not found'}

        except Exception as e:
            error_class = e.__class__.__name__
            detail = e.args[0]
            logger.warning(f"Forgot PW Error: [{error_class}] detail: {detail}")
            return {'status': 1, 'result': str(e), "error": detail}



@api_ns.route('/api/auth', methods=['GET'])
@jwt_required()
class Auth(Resource):
    @handle_request_exception
    def get(self):
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        return {'status': 0, 'result': user.username}

# @api_ns.route('/api/addtruck', methods=['GET'])
# def truck(Resource):
#     try:
#         data = api.payload
#         name = data.get('name')
#         model = data.get('model')
#         number = data.get('number')
#         track_day = data.get('track_day')
#         truck_day = data.get('truck_day')

#         if Truck.query.filter_by(name=name).first():
#             return ({'status':'1', 'result': 'Truck already exists'}), 400
        
#         current_user_id = User.query.get(get_jwt_identity())

#         if current_user_id.permission < 1:
#             return ({'status':'1', 'result': 'Permission denied'}), 400
        
#         new_truck = Truck(name=name, model=model, number=number, track_day=track_day, truck_day=truck_day)
#         db.session.add(new_truck)
#         db.session.commit()
#         return ({'status':'0', 'result': '新增成功'}), 201
#     except Exception as e:
#         error_class = e.__class__.__name__
#         detail = e.args[0]
#         logger.warning(f"Add Truck Error: [{error_class}] detail: {detail}")
#         return ({'status':'1', 'result': str(e)}), 500

   
# @api_ns.route("/users")
# def user_list():
#     users = db.session.execute(db.select(User).order_by(User.username)).scalars()

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
