import os
import random
import string
from datetime import timedelta

from dotenv import load_dotenv
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity, create_refresh_token
)
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
from models import db, User
from logger import logging
from util import handle_request_exception

bcrypt = Bcrypt()
logger = logging.getLogger(__file__)
jwt = JWTManager(app)

load_dotenv()

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("SQL_SERVER")
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY')
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(minutes=10)
app.config["JWT_REFRESH_TOKEN_EXPIRES"] = timedelta(days=30) 
app.config['API_KEY']= os.environ.get('API_SECRET_KEY')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False 
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
        """
        註冊
        """
        data = api.payload
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')
        try:
            if User.query.filter_by(username=username).first():
                return ({'status':1, 'result': 'Username already exists'}), 400
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
            return {'status':1, 'result': error_class, 'error': detail}

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
            # if e.__class__.__name__ == 'RuntimeError:':
            #     return {'status':1, 'result': 'JWT憑證已經過期，請重新登入'}
            error_class = e.__class__.__name__
            detail = e.args[0]
            logger.warning(f"Forgot PW Error: [{error_class}] detail: {detail}")
            return {'status': 1, 'result': str(e), "error": detail}


@api_ns.route('/api/auth', methods=['GET'])
class Test(Resource):
    @api.doc(params={'jwt': ''})
    @handle_request_exception
    @jwt_required()
    def get(self):
        user = User.query.get(get_jwt_identity())
        return {'status': 0, 'result': user.username}

@api_ns.route("/refresh", methods=["POST"])
class Refresh(Resource):
    @handle_request_exception
    @api.expect(refresh_input_payload)
    @api.marshal_with(general_output_payload)
    @jwt_required(refresh=True)
    def post(self):
        current_user = get_jwt_identity()
        new_access_token = create_access_token(identity=current_user)
        return {"access_token":new_access_token}



   
# @api_ns.route("/users")
# def user_list():
#     users = db.session.execute(db.select(User).order_by(User.username)).scalars()

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
