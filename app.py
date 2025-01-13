import os
from flask import Flask, request, jsonify
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity
)
from models import db, User, Truck
from logger import logging

app = Flask(__name__)
logger = logging.getLogger(__file__)
jwt = JWTManager(app)

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL")  # 環境變數中的資料庫 URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False  # 關閉事件追蹤，提升性能

db.metadata.init_app(app)
with app.app_context():
    db.metadata.create_all()
    logger.info('DB init done')

# class AuthorizationManager():
#     def __init__(self):
#         self.permission = 0

#     def check_permission(self, user_id):
#         user = User.query.get(user_id)
#         if user:
#             self.permission = user.permission
#         return self.permission

@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')

        if User.query.filter_by(username=username).first():
            return jsonify({'status':'1', 'message': 'Username already exists'}), 400
        if User.query.filter_by(email=email).first():
            return jsonify({'status':'1','message': 'Email already exists'}), 400

        new_user = User(username=username, email=email)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        logger.info(f'Register user:{username} id:{new_user.id}')
        return jsonify({'status':'0', 'message': '註冊成功}'}), 201
    except Exception as e:
        error_class = e.__class__.__name__
        detail = e.args[0]
        logger.warning(f"Register Error: [{error_class}] detail: {detail}")
        return jsonify({'status':'1', 'message': str(e)}), 500

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            access_token = create_access_token(identity=user.id)
            return jsonify({'status':'0', 'access_token': access_token}), 200

        return jsonify({'status':'1', 'message': '憑證無效'}), 401
    except Exception as e:
        error_class = e.__class__.__name__
        detail = e.args[0]
        logger.warning(f"login Error: [{error_class}] detail: {detail}")
        return jsonify({'status':'1', 'message': str(e)}), 500

@app.route('/api/forgot', methods=['POST'])
def forgot():
    try:
        data = request.get_json()
        email = data.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            db.session.query(User).filter_by(email=email).update({'password': '12345'})
            db.session.commit()
            return jsonify({'message': 'Email sent'}), 200
        return jsonify({'message': 'User not found'}), 404
    except Exception as e:
        error_class = e.__class__.__name__
        detail = e.args[0]
        logger.warning(f"Forgot PW Error: [{error_class}] detail: {detail}")
        return jsonify({'status':'1', 'message': str(e)}), 500

@app.route('/api/auth', methods=['GET'])
@jwt_required()
def protected():
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    return jsonify(logged_in_as=user), 200
    return jsonify({'message': f'Welcome {user.username}!'}), 200

@app.route('/api/addtruck', methods=['GET'])
def truck(request):
    try:
        data = request.get_json()
        name = data.get('name')
        model = data.get('model')
        number = data.get('number')
        track_day = data.get('track_day')
        truck_day = data.get('truck_day')

        if Truck.query.filter_by(name=name).first():
            return jsonify({'status':'1', 'message': 'Truck already exists'}), 400
        
        current_user_id = User.query.get(get_jwt_identity())

        if current_user_id.permission < 1:
            return jsonify({'status':'1', 'message': 'Permission denied'}), 400
        
        new_truck = Truck(name=name, model=model, number=number, track_day=track_day, truck_day=truck_day)
        db.session.add(new_truck)
        db.session.commit()
        return jsonify({'status':'0', 'message': '新增成功'}), 201
    except Exception as e:
        error_class = e.__class__.__name__
        detail = e.args[0]
        logger.warning(f"Add Truck Error: [{error_class}] detail: {detail}")
        return jsonify({'status':'1', 'message': str(e)}), 500

   
@app.route("/users")
def user_list():
    users = db.session.execute(db.select(User).order_by(User.username)).scalars()

if __name__ == '__main__':
    app.run(debug=True)
