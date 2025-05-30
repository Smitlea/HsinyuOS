from flask import Flask
from flask_restx import Api, Namespace, fields

app = Flask("app")
api = Api(app, version='0.0.1', title='HsinyuOS Open API', doc='/api/doc')
api_ns = Namespace("HsinyuOS", "all right reserve", path="/")
api_test = Namespace("test", "尚未測試完成API", path="/")
api_notice = Namespace("Notice", "注意事項API", path="/")
api_crane = Namespace("Crane", "吊車API", path="/")



api.add_namespace(api_ns)
api.add_namespace(api_crane)
api.add_namespace(api_notice)
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
        "start_date": fields.String(required=True, default="2021-01-01 00:00:00"),
        "end_date": fields.String(required=True, default="2021-01-01 00:00:00"),
        "reason": fields.String(required=True, default=""),
    },
)

login_payload = api_ns.model(
    "登入輸入",
    {
        "username": fields.String(required=True, default="smitlea"),
        "password": fields.String(required=True, default="123"),
    },
)

login_output_payload = api_ns.model(
    "登入輸出",
    {
        "status": fields.Integer(
            required=True, description="0 for success, 1 for failure", default=1
        ),
        "result": fields.String(required=True, default="1"),
        'refresh_token': fields.String(required=False, description='Refresh token'),
        'error': fields.String(required=False, default=""),
    },
)

refresh_input_payload = api_ns.model(
    "刷新JWT輸入",
    {
        "refresh_token": fields.String(required=True, description="Refresh token"),
    },
)

forgot_password_payload = api_ns.model('忘記密碼輸入', {
    'email': fields.String(required=True, description='User email for password reset')
})

add_usage_payload = api_ns.model(
    '新增使用紀錄輸入',
    {
        'usage_date': fields.String(
            required=False,
            description='使用日期 (YYYY-MM-DD)，不填則預設為今日',
            default='2025-03-03'
        ),
        'daily_hours': fields.Integer(
            required=False,
            description='當日使用小時 (預設 8)',
            default=8
        ),
    }
)

# 新增注意事項
add_notice_payload = api_ns.model(
    '新增注意事項輸入',
    {
        'notice_date': fields.String(
            required=False,
            description='注意事項日期 (YYYY-MM-DD)，不填則預設為今日',
            default='2025-03-03'
        ),
        'status': fields.String(
            required=True,
            description='注意事項狀態 (待修/異常/現場)',
            default='待修'
        ),
        'title': fields.String(
            required=True,
            description='注意事項大綱',
            default='吊臂異常'
        ),
        'description': fields.String(
            required=False,
            description='注意事項的詳細描述',
            default='檢查到吊臂有異常聲音，需要技師檢修。'
        ),
    }
)

# 新增維修記錄
add_maintenance_payload = api_ns.model(
    "AddMaintenance", {
        "maintenance_date": fields.String(example="2025-05-30"),
        "title":    fields.String(required=True,  example="更換液壓油"),
        "note":     fields.String(required=False, example="定期保養"),
        "material": fields.String(required=False, example="液壓油 20L"),
        # 進階欄位：文件上標 Optional，實際由程式面控制
        "vendor":       fields.String(example="維修達人有限公司"),
        "vendor_cost":  fields.Float(example=12000),
        "parts_vendor": fields.String(example="忠興油品行"),
        "parts_cost":   fields.Float(example=3400),
    }
)

add_crane_payload = api_ns.model('新增吊車輸入', {
        'crane_number': fields.String(required=True, description='代號', default="ABC-123"),
        'crane_type': fields.String(required=True, description='圖片', default="輪式"),
        'initial_hours': fields.String(required=True, description='初始小時', default=100),
        'coordinates': fields.String(required=True, description='地點', default='台中港'),
        "photo": fields.List(fields.String, required=False, example="path/to/photo.jpg")
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

site_input_payload = api_ns.model(
    "工地輸入",
    {
        "vendor":   fields.String(required=True,  example="大林營造"),
        "location": fields.String(required=True,  example="台北市中山區民權東路"),
        'coordinates': fields.String(required=False, example="25.0478,121.5171"),
        "photo": fields.List(fields.String, required=False, example="path/to/photo.jpg")
    },
)

site_output_payload = api_ns.model(
    "工地輸出",
    {
        "status": fields.Integer(
            required=True,
            description="0 for success, 1 for failure",
            default=1
        ),
        "result": fields.Nested(
            api_ns.model(
                "工地輸出內容",
                {
                    "id": fields.String(required=True, example="123456"),
                    "vendor": fields.String(required=True, example="大林營造"),
                    "location": fields.String(required=True, example="台北市中山區民權東路"),
                    "latitude": fields.Float,     
                    "longitude": fields.Float,
                    "photo": fields.List(fields.String, required=False, example="<base64 string>"),
                    "created_at": fields.String(required=True, example="2023-10-01 12:00:00"),
                    "note": fields.String(required=False, example="工地備註"),
                },
            )
        )
    }
)
site_item_payload = api_ns.model(
    "工地",
    {
        "id":         fields.String,
        "vendor":     fields.String,
        "location":   fields.String,
        "latitude": fields.Float,     
        "longitude": fields.Float,   
        "note": fields.String,
        "created_at": fields.String,
    },
)

site_list_output = api_ns.model(
    "工地列表輸出",
    {
        "status": fields.Integer(example=1),
        "result": fields.List(fields.Nested(site_item_payload)),
    },
)


