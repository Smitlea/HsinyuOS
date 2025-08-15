from datetime import datetime
import pytz

from flask import request
from flask_restx import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import selectinload  
from static.models import (
    db, Crane, _sum_usage_hours, MaintenanceRecord,
    _cycle_info, _due_parts_for_cycle, _consumables_hints_for_parts
)

from static.payload import (
    api_ns, add_task_payload,
    general_output_payload, 
    add_task_maint_payload, 
    work_record_input_payload
)
from static.util import handle_request_exception
from static.logger import logging


from flask import request, jsonify


# ────────── 週期常數與規則 ──────────
CYCLE_HOURS = 500
CYCLES_PER_ROUND = 12
ROUND_HOURS = CYCLE_HOURS * CYCLES_PER_ROUND  # 6000

PART_LABELS = {
    "engine_oil": "機油",
    "main_hoist_gear_oil": "主捲齒輪油",
    "lion_head_gear_oil": "獅頭齒輪油",
    "aux_hoist_gear_oil": "補捲齒輪油",
    "luffing_gear_oil": "起伏齒輪油",
    "slewing_gear_oil": "旋回齒輪油",
    "circulation_oil": "循環油",
    "belts": "皮帶",
    "sprocket": "齒盤",
    "sprocket_oiling": "齒盤上油",
}

# 需要紀錄的濾心（與哪些油品一起更換）
CONSUMABLES_HINTS = {
    "engine_oil": ["engine_oil_filter"],  # 機油濾心
    # 循環油：排水、進油、回油濾心
    "circulation_oil": ["circulation_drain_filter", "circulation_inlet_filter", "circulation_return_filter"],
}

ALLOWED_PARTS = set(PART_LABELS.keys())
ALLOWED_CONSUMABLES = {"engine_oil_filter", "circulation_drain_filter", "circulation_inlet_filter", "circulation_return_filter"}


# ───────────────── GET：查該吊車「當下週期」需更換 ─────────────────
@api_ns.route("/api/cranes/<int:crane_id>/maintenance/due", methods=["GET"])
def get_due_parts_for_crane(crane_id: int):
    total_hours = _sum_usage_hours(crane_id)
    if total_hours is None:
        return jsonify({"error": f"找不到吊車 id={crane_id}"}), 404

    info = _cycle_info(total_hours)
    due_parts = _due_parts_for_cycle(info["cycle_index"])
    consumables_hint = _consumables_hints_for_parts(due_parts)

    # 該吊車、該週期已更換的零件
    records = (
        MaintenanceRecord.query
        .filter(
            MaintenanceRecord.crane_id == crane_id,
            MaintenanceRecord.maintenance_hours >= info["cycle_start"],
            MaintenanceRecord.maintenance_hours <  info["cycle_end"],
        ).all()
    )
    already = set()
    for r in records:
        if r.parts:
            already.update(r.parts)

    pending = [p for p in due_parts if p not in already]

    return jsonify({
        "crane_id": crane_id,
        "total_hours": total_hours,
        "cycle": {
            "index": info["cycle_index"],   # 1..12
            "start": info["cycle_start"],   # 含
            "end": info["cycle_end"],       # 不含
            "unit_hours": CYCLE_HOURS,
            "round_hours": ROUND_HOURS
        },
        "due_parts": [{"code": p, "label": PART_LABELS[p]} for p in due_parts],
        "consumables_hint": consumables_hint,
        "already_replaced": sorted(already),
        "pending_parts": pending
    }), 200


# ───────────────── POST：在該吊車底下新增保養紀錄 ─────────────────
@app.route("/api/cranes/<int:crane_id>/maintenance", methods=["POST"])
def create_maintenance_for_crane(crane_id: int):
    data = request.get_json(silent=True) or {}
    maintenance_hours = data.get("maintenance_hours")
    date_str = data.get("date")
    parts = data.get("parts") or []
    consumables = data.get("consumables") or []
    note = data.get("note")

    # 必填
    if maintenance_hours is None or not date_str:
        return jsonify({"error": "必填欄位：maintenance_hours、date"}), 400

    # 吊車存在性
    crane = Crane.query.get(crane_id)
    if not crane:
        return jsonify({"error": f"找不到吊車 id={crane_id}"}), 404

    # 日期格式
    try:
        record_date = datetime.date.fromisoformat(date_str)
    except Exception:
        return jsonify({"error": "date 格式需為 YYYY-MM-DD"}), 400

    # 驗證零件代碼
    parts = list(dict.fromkeys(parts))
    invalid_parts = [p for p in parts if p not in ALLOWED_PARTS]
    if invalid_parts:
        return jsonify({"error": f"parts 包含未知代碼: {invalid_parts}"}), 400

    # 驗證耗材代碼
    consumables = list(dict.fromkeys(consumables))
    invalid_cons = [c for c in consumables if c not in ALLOWED_CONSUMABLES]
    if invalid_cons:
        return jsonify({"error": f"consumables 包含未知代碼: {invalid_cons}"}), 400

    # 以「保養時數」所屬週期做重複檢查（同吊車、同週期避免重複更換）
    info_at = _cycle_info(int(maintenance_hours))
    existing = (
        MaintenanceRecord.query
        .filter(
            MaintenanceRecord.crane_id == crane_id,
            MaintenanceRecord.maintenance_hours >= info_at["cycle_start"],
            MaintenanceRecord.maintenance_hours <  info_at["cycle_end"],
        ).all()
    )
    replaced = set()
    for r in existing:
        if r.parts:
            replaced.update(r.parts)

    # 本次要新增但已在該週期做過的 → 視為跳過
    new_parts = [p for p in parts if p not in replaced]
    skipped_parts = [p for p in parts if p in replaced]

    if not new_parts and parts:
        return jsonify({
            "error": "該週期內此吊車的這些零件已更換過",
            "skipped_parts": skipped_parts,
            "cycle": info_at
        }), 409

    rec = MaintenanceRecord(
        crane_id=crane_id,
        record_date=record_date,
        maintenance_hours=int(maintenance_hours),
        parts=new_parts or parts,  # 若傳空陣列，保留原樣（可紀錄僅耗材）
        consumables=(consumables or None),
        note=note,
        created_by=(g.user.id if getattr(g, "user", None) else None),
    )
    db.session.add(rec)
    db.session.commit()

    return jsonify({
        "message": "ok",
        "record": rec.to_dict(),
        "cycle": info_at,
        "skipped_parts": skipped_parts
    }), 201
