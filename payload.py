from flask import Flask
from flask_restx import Api, Namespace, Resource, reqparse, fields

app = Flask("app")
api = Api(app, version='0.0.1', title='HsinyuOS API規格', doc='/api/doc')
api_ns = Namespace("HsinyuOS", "all right reserve", path="/")
api_test = Namespace("test", "Test API Here", path="/")

api.add_namespace(api_ns)
api.add_namespace(api_test)
    

register_payload = api_ns.model(
    "註冊輸入",
    {
        "username": fields.String(required=True, default="Smitlea"),
        "email": fields.String(required=True, default="a@gmail.com"),
        "password": fields.String(required=True, default="123"),
    },
)
leave_payload = api_ns.model(
    "請假輸入",
    {
        "user_id": fields.Integer(required=True, default=1),
        "start_date": fields.String(required=True, default="2021-01-01 00:00:00"),
        "end_date": fields.String(required=True, default="2021-01-01 00:00:00"),
        "reason": fields.String(required=True, default=""),
    },
)

login_payload = api_ns.model(
    "登入輸入",
    {
        "username": fields.String(required=True, default="3e4f5e4f-3e4f-3e4f-3e4f-3e4f5e4f5e4f"),
        "password": fields.String(required=True, default="123"),
    },
)

forgot_password_payload = api_ns.model('ForgotPasswordPayload', {
    'email': fields.String(required=True, description='User email for password reset')
})

add_crane_payload = api_ns.model('AddTruck', {
        'name': fields.String(required=True, description='代號'),
        'img': fields.String(required=True, description='圖片'),
        'model': fields.String(required=True, description='車型'),
        'number': fields.String(required=True, description='車號'),
        'track_lifespan': fields.Integer(required=True, description='履帶壽命'),
        'crane_lifespan': fields.Integer(required=True, description='吊車壽命')
})

general_output_payload = api_ns.model(
    "general Output",
    {
        "status": fields.Integer(
            required=True, description="0 for success, 1 for failure", default=1
        ),
        "result": fields.String(required=True, default="1"),
        "error": fields.String(required=False, default=""),
    },
)