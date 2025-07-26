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

add_task_payload = api_ns.model("AddDailyTask", {
    "task_date":   fields.String(description="YYYY-MM-DD，預設今天"),
    "vendor":      fields.String(required=True),
    "site_id":     fields.String(required=True),       # 或 site_location 字串二擇一
    "crane_number":fields.String(required=True),       # 由程式轉成 crane_id
    "work_time":   fields.String(required=True, example="08:00-17:00"),
    "note":        fields.String,
})

add_task_maint_payload = api_ns.model("AddTaskMaintenance", {
    
    "maintenance_date": fields.String(description="YYYY-MM-DD，預設今天"),
    "description":      fields.String(required=True),
})

# 新增維修記錄
notice_color_model = api_ns.model(
    "NoticeColor",
    {
        "status_name": fields.String(
            required=True, description="狀態名稱", example="保養"
        ),
        "color": fields.String(
            required=True, description="Hex 或 CSS 顏色名稱", example="#ffa500"
        ),
    },
)

add_maintenance_payload = api_ns.model(
    "AddMaintenance", {
        "maintenance_date": fields.String(example="2025-05-30"),
        "title":    fields.String(required=True,  example="更換液壓油"),
        "note":     fields.String(required=False, example="定期保養"),
        "material": fields.String(required=False, example="液壓油 20L"),
        "photo": fields.List(fields.String(description="Base64 編碼圖檔"), max_items=5, required=False),
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
        "has_photo": fields.Boolean
    },
)

site_list_output = api_ns.model(
    "工地列表輸出",
    {
        "status": fields.Integer(example=1),
        "result": fields.List(fields.Nested(site_item_payload)),
    },
)

# ─── 使用者暱稱清單 ─────────────────────
username_output = api_ns.model(
    "UsernameItem",
    {
        "name": fields.String(example="smitlea"),
    },
)

work_record_input_payload = api_ns.model(
    "WorkRecordInput",
    {
        "record_date": fields.String(required=False, description="紀錄日期", example="2025-06-26"),
        "vendor": fields.String(required=True, description="供應商名稱", example="大林營造"),
        "qty_120": fields.Integer(default=0, description="120噸吊車數量"),
        "qty_200": fields.Integer(default=0, description="200噸吊車數量"),
        "assistants": fields.List(
            fields.String,
            default=[],
            description="協助人員列表",
            example=["杰克", "gary", "微笑"]
        )
    }
)

# —— 貨車 —— #
add_truck_payload = api.model("AddTruck", {
    "truck_number": fields.String(required=True, description="車號"),
    "latitude":     fields.Float(required=False),
    "longitude":    fields.Float(required=False),
})

# —— 油桶 IN / OUT —— #
add_drum_payload = api.model("DrumRecord", {
    "record_date": fields.String(required=False, description="YYYY-MM-DD"),
    "io_type":     fields.String(enum=["IN", "OUT"], required=True),
    "quantity":    fields.Float(required=True, min=0),
    "unit_price":  fields.Float(required=False, description="IN 時必填 1 位小數"),
    "crane_id":    fields.Integer(required=False, description="OUT 時必填，被加油的吊車 ID")
})


# —— 貨車加油 —— #
add_fuel_payload = api.model("FuelRecord", {
    "record_date": fields.String(required=False, description="YYYY-MM-DD、空值為今天"),
    "quantity":    fields.Float(required=True, min=0),
    "unit_price":  fields.Float(required=True, description="1 位小數"),
})

announcement_payload = api_ns.model(
    "Announcement",
    {
        "title": fields.String(required=True, description="公告標題"),
        "content": fields.String(required=True, description="公告內容"),
        "photo": fields.List(fields.String, required=False, example="path/to/photo.jpg"),
        'coordinates': fields.String(required=True, description='地點', default='台中港'),
    }
)

announcemnt_color_model = api_ns.model(
    "NoticeColor",
    {
        "status_name": fields.String(
            required=True, description="狀態名稱", example="保養"
        ),
        "color": fields.String(
            required=True, description="Hex 或 CSS 顏色名稱", example="#ffa500"
        ),
    },
)
