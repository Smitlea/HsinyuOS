import datetime
from decimal import Decimal

from flask import g
from flask_restx import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import joinedload
from static.models import db, User, Truck, OilDrumRecord, TruckFuelRecord, Crane
from static.util import permission_required

from static.payload import (
    api_ns, api, api_crane, api_test, api_notice,
    add_truck_payload, add_drum_payload, add_fuel_payload
)
from static.logger import logging

logger = logging.getLogger(__file__)

# ------------------------------
#  貨車 (Truck) GET/POST API
# ------------------------------
@api.route("/api/trucks", methods=["GET", "POST"])
class TruckList(Resource):
    @jwt_required()
    def get(self):
        result = []
        for t in Truck.query.all():
            result.append({
                "id":            t.id,
                "truck_number":  t.truck_number,
                "drum_remain":   float(t.drum_remain()),
                "fuel_remain":   float(t.fuel_remain()),
            })
        return {"status": "0", "result": result}, 200

    @jwt_required()
    @api.expect(add_truck_payload)
    def post(self):
        data = api.payload or {}
        truck_number = data.get("truck_number")
        if not truck_number:
            return {"status": 1, "result": "缺少車號"}, 400
        if Truck.query.filter_by(truck_number=truck_number).first():
            return {"status": 1, "result": "車號已存在"}, 409

        truck = Truck(truck_number=truck_number)
        db.session.add(truck)
        db.session.commit()
        return {"status": "0", "result": "貨車創建成功"}, 200


@api.route("/api/trucks/<int:truck_id>", methods=["GET"])
class TruckDetail(Resource):
    @jwt_required()
    def get(self, truck_id):
        truck = Truck.query.get(truck_id)
        if not truck:
            return {"status": 1, "result": "找不到指定貨車"}, 404
        return {"status": "0", "result": {
            "id":           truck.id,
            "truck_number": truck.truck_number,
            "drum_remain":  float(truck.drum_remain()),
            "fuel_remain":  float(truck.fuel_remain()),
            "latitude":     truck.latitude,
            "longitude":    truck.longitude,
        }}, 200
    
# ------------------------------
#  油桶紀錄OilDrumRecord GET/POST
# ------------------------------
@api.route("/api/trucks/<int:truck_id>/drums", methods=["GET", "POST"])
class DrumRecordList(Resource):
    """
    GET：油桶出入紀錄清單
    POST：新增 IN / OUT
    """
    @jwt_required()
    def get(self, truck_id):
        t = Truck.query.get(truck_id)
        if not t:
            return {"status": 1, "result": "找不到指定貨車"}, 404
        rows = OilDrumRecord.query.filter_by(truck_id=truck_id).order_by(
                    OilDrumRecord.record_date.desc()
                ).all()
        return {"status": "0", "result": [
            {
                "id": r.id,
                "record_date": r.record_date.isoformat(),
                "io_type": r.io_type,
                "quantity": float(r.quantity),
                "unit_price": float(r.unit_price) if r.unit_price else None
            } for r in rows]}, 200
    


    @jwt_required()
    @api.expect(add_drum_payload)
    def post(self, truck_id):
        data = api.payload or {}
        io_type = data.get("io_type")
        qty     = data.get("quantity")
        price   = data.get("unit_price")
        crane_id = data.get("crane_id")

        # ---------- 基本驗證 ---------- #
        if qty is None or qty < 0:
            return {"status": 1, "result": "油量需為非負數"}, 400
        if io_type == "IN":
            if price is None:
                return {"status": 1, "result": "入油必須填單價"}, 400
            if crane_id is not None:
                return {"status": 1, "result": "入油不可指定吊車 crane_id"}, 400
        else:  # OUT
            if price is not None:
                return {"status": 1, "result": "出油不可填單價"}, 400
            if crane_id is None:
                return {"status": 1, "result": "出油必須指定吊車 crane_id"}, 400
            # 確認吊車存在
            if not Crane.query.get(crane_id):
                return {"status": 1, "result": "找不到指定吊車"}, 404
        # ---------- 檢查餘量不可為負 ---------- #
        truck = Truck.query.get(truck_id)
        if not truck:
            return {"status": 1, "result": "找不到指定貨車"}, 404
        if io_type == "OUT" and qty > truck.drum_remain():
            return {"status": 1, "result": "油桶餘量不足"}, 400

        rec = OilDrumRecord(
            truck_id=truck_id,
            crane_id=crane_id,
            record_date=datetime.date.fromisoformat(
                data.get("record_date") or datetime.date.today().isoformat()
            ),
            io_type=io_type,
            quantity=qty,
            unit_price=price
        )
        db.session.add(rec)
        db.session.commit()
        return {"status": "0", "result": "Drum record created."}, 200
# ------------------------------
#  油桶單筆更新/軟刪除 PUT/DELETE
# ------------------------------
@api.route("/api/drums/<int:record_id>", methods=["PUT", "DELETE"])
class DrumRecord(Resource):
    @jwt_required()
    def put(self, record_id):
        user = User.query.get(get_jwt_identity())
        if not user or user.permission < 1:
            return {"status": 1, "result": "使用者權限不足"}, 403

        rec = OilDrumRecord.query.get(record_id)
        if not rec:
            return {"status": 1, "result": "找不到指定油桶紀錄"}, 404
        if rec.is_deleted:
            return {"status": 1, "result": "紀錄已刪除"}, 410
        rec.updated_by = user.id 

        data = api.payload or {}

        # ------- 抓原值或新值 ------- #
        io_type   = data.get("io_type", rec.io_type)
        qty       = data.get("quantity", rec.quantity)
        unit_price= data.get("unit_price", rec.unit_price)


        # ---------- 基本驗證 ---------- #
        if qty is None or qty < 0:
            return {"status": 1, "result": "油量需為非負數"}, 400
        if io_type == "IN" and unit_price is None:
            return {"status": 1, "result": "入油必須填油量單價"}, 400
        if io_type == "OUT" and "unit_price" in data:
            return {"status": 1, "result": "出油不可填油量單價"}, 400
        if unit_price is not None and unit_price < 0:
            return {"status": 1, "result": "單價需為非負數"}, 400

        # ---------- 模擬新餘量 ---------- #
        truck = rec.truck
        total_in = sum(r.quantity for r in truck.drum_records if r.io_type == "IN" and not r.is_deleted and r.id != rec.id)
        total_out = sum(r.quantity for r in truck.drum_records if r.io_type == "OUT" and not r.is_deleted and r.id != rec.id)

        if io_type == "IN":
            total_in += qty
        else:
            total_out += qty

        if total_out > total_in:
            return {"status": 1, "result": "更新後出油超過油桶殘量"}, 400

        # ---------- 實際更新 ---------- #
        for f in ("record_date", "io_type", "quantity", "unit_price"):
            if f in data:
                setattr(rec, f, data[f])

        db.session.commit()
        return {"status": "0", "result": "油桶紀錄已成功更新"}, 200

    @jwt_required()
    def delete(self, record_id):
        user = User.query.get(get_jwt_identity())
        if user.permission < 1:
            return {"status": "1", "result": "使用者權限不足"}, 403
        rec = OilDrumRecord.query.get(record_id)
        if not rec:
            return {"status": 1, "result": "找不到指定油桶紀錄"}, 404
        rec.updated_by = user.id 
        rec.is_deleted = True
        db.session.commit()
        return {"status": "0", "result": "油桶紀錄已成功刪除"}, 200
    
# ------------------------------
#  貨車加油紀錄 GET/POST
# ------------------------------
@api.route("/api/trucks/<int:truck_id>/fuels", methods=["GET", "POST"])
class FuelRecordList(Resource):
    """
    GET：加油紀錄
    POST：新增加油
    """
    @jwt_required()
    def get(self, truck_id):
        if not Truck.query.get(truck_id):
            return {"status": 1, "result": "找不到指定貨車"}, 404
        rows = TruckFuelRecord.query.filter_by(
                truck_id=truck_id
            ).order_by(TruckFuelRecord.record_date.desc()).all()
        return {"status": "0", "result": [
            {
                "id": r.id,
                "record_date": r.record_date.isoformat(),
                "quantity": float(r.quantity),
                "unit_price": float(r.unit_price)
            } for r in rows]}, 200

    @jwt_required()
    @api.expect(add_fuel_payload)
    def post(self, truck_id):
        data = api.payload or {}
        qty   = data.get("quantity")
        price = data.get("unit_price")

        if qty is None or qty < 0 or price is None or price < 0:
            return {"status": 1, "result": "quantity / unit_price 必須為非負"}, 400

        rec = TruckFuelRecord(
            truck_id=truck_id,
            record_date= datetime.date.fromisoformat(
                data.get("record_date") or datetime.date.today().isoformat()
            ),
            quantity=qty,
            unit_price=price
        )
        db.session.add(rec)
        db.session.commit()
        return {"status": "0", "result": "Fuel record created."}, 200

@api.route("/api/fuels/<int:record_id>", methods=["PUT", "DELETE"])
class FuelRecord(Resource):
    @jwt_required()
    def put(self, record_id):
        user = User.query.get(get_jwt_identity())
        if user.permission < 1:
            return {"status": "1", "result": "使用者權限不足"}, 403
        record = TruckFuelRecord.query.get(record_id)
        if record is None:
            return {"status": 1, "result": "找不到指定加油紀錄"}, 400
        if record.is_deleted:
            return {"status": 1, "result": "紀錄已刪除"}, 410
        data = api.payload or {}
        for f in ("recordord_date", "quantity", "unit_price"):
            if f in data:
                setattr(record, f, data[f])
        if record.quantity < 0 or record.unit_price < 0:
            return {"status": 1, "result": "油量/單價 不可為負數"}, 400
        record.updated_by = user.id
        db.session.commit()
        return {"status": "0", "result": "貨車燃油已更新成功."}, 200

    @jwt_required()
    @permission_required(1)
    def delete(self, record_id):
        record = TruckFuelRecord.query.get(record_id)
        if not record:
            return {"status": 1, "result": "找不到指定加油紀錄"}, 404
        record.updated_by = g.current_user.id
        record.is_deleted = True
        db.session.commit()
        return {"status": "0", "result": "貨車燃油紀錄已成功刪除"}, 200