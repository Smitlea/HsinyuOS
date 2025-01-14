from flask import Flask
from flask_restx import Api, Namespace, Resource, reqparse, fields

app = Flask("app")
api = Api(app, version='0.0.1', title='奇美OpenAI Automation模擬', doc='/api/doc')
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

login_payload = api_ns.model(
    "登入輸入",
    {
        "username": fields.String(required=True, default="3e4f5e4f-3e4f-3e4f-3e4f-3e4f5e4f5e4f"),
        "password": fields.String(required=True, default="123"),
    },
)

forgot_password_payload = api.model('ForgotPasswordPayload', {
    'email': fields.String(required=True, description='User email for password reset')
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