# maintenance_record_api.py
from datetime import datetime, date
import pytz

from flask import request   # 不要用 jsonify，讓 RESTX 幫你序列化
from flask_restx import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import func

import datetime
from static.models import (
    db, Crane, DailyTask, MaintenanceRecord, User, CraneMaintenanceState, CraneWireRope,
    CraneWireRopeLog, WIRE_ROPE_THRESHOLD,
    _sum_usage_hours, _sync_usage_hours_cache, _cycle_info, _due_parts_for_cycle,
    _maintenance_alert, _wire_rope_alert, CYCLE_HOURS, CYCLES_PER_ROUND, ROUND_HOURS
)
from static.payload import api_ns
from static.util import handle_request_exception
from static.logger import logging

logger = logging.getLogger(__file__)
tz = pytz.timezone('Asia/Taipei')

# 英文代碼 → 中文顯示
PART_LABELS = {
    "engine_oil": "機油",
    "main_hoist_gear_oil": "主捲",
    "lion_head_gear_oil": "獅頭",
    "aux_hoist_gear_oil": "補捲",
    "luffing_gear_oil": "起伏",
    "slewing_gear_oil": "旋回",
    "circulation_oil": "循環油",
    "belts": "皮帶齒盤",
}
# 中文顯示 → 英文代碼（自動反轉）
LABEL_TO_CODE = {v: k for k, v in PART_LABELS.items()}


CONSUMABLES_HINTS = {
    "engine_oil": ["engine_oil_filter", "fuel_oil_filter"],
    "circulation_oil": ["braker_drain_filter", "circulation_drain_filter", "circulation_inlet_filter", "circulation_return_filter"],
}
# 耗材代碼 → 中文顯示（自訂：可依你習慣調整用詞）
CONSUMABLE_LABELS = {
    "engine_oil_filter": "機油芯",
    "fuel_oil_filter": "柴油芯",
    "braker_drain_filter": "煞車",
    "circulation_drain_filter": "排水",
    "circulation_inlet_filter": "進油",
    "circulation_return_filter": "回油",
}
CONSUMABLE_LABEL_TO_CODE = {v: k for k, v in CONSUMABLE_LABELS.items()}


ALLOWED_PARTS = set(PART_LABELS.keys())
ALLOWED_CONSUMABLES = set(CONSUMABLE_LABELS.keys())

# 補捲/起伏/旋回 在前端顯示時合併為「其他」
GROUPED_AS_OTHER = {"aux_hoist_gear_oil", "luffing_gear_oil", "slewing_gear_oil"}

def _consumables_hints_for_parts(parts: list[str]) -> list[str]:
    hints: list[str] = []
    for p in parts:
        hints.extend(CONSUMABLES_HINTS.get(p, []))
    return sorted(set(hints))

# ────────── 小工具：中英轉換 / 格式化 ──────────
def _normalize_part_codes(items: list[str]) -> tuple[list[str], list[str]]:
    """把輸入（可能是中文或英文代碼）轉成英文代碼；回傳 (codes, unknown_items)"""
    codes, unknown = [], []
    seen = set()
    for raw in items or []:
        s = (raw or "").strip()
        if not s:
            continue
        if s in ALLOWED_PARTS:
            code = s
        elif s in LABEL_TO_CODE:
            code = LABEL_TO_CODE[s]
        else:
            unknown.append(s)
            continue
        if code not in seen:
            seen.add(code)
            codes.append(code)
    return codes, unknown

def _normalize_consumable_codes(items: list[str]) -> tuple[list[str], list[str]]:
    """把輸入（可能是中文或英文代碼）轉成英文代碼；回傳 (codes, unknown_items)"""
    codes, unknown = [], []
    seen = set()
    for raw in items or []:
        s = (raw or "").strip()
        if not s:
            continue
        if s in ALLOWED_CONSUMABLES:
            code = s
        elif s in CONSUMABLE_LABEL_TO_CODE:
            code = CONSUMABLE_LABEL_TO_CODE[s]
        else:
            unknown.append(s)
            continue
        if code not in seen:
            seen.add(code)
            codes.append(code)
    return codes, unknown

def _code_label_list(codes: list[str], kind: str = "part") -> list[str]:
    """把代碼列表轉成中文顯示標籤，part 類型會將補捲/起伏/旋回合併為「其他」"""
    if kind == "part":
        labels: list[str] = []
        other_added = False
        for c in codes:
            if c in GROUPED_AS_OTHER:
                if not other_added:
                    labels.append("其他")
                    other_added = True
            else:
                labels.append(PART_LABELS.get(c, c))
        return labels
    else:
        return [CONSUMABLE_LABELS.get(c, c) for c in codes]

# 小工具：前端展示的 parts（代碼→中文，並依規則加上濾芯）
# 規則：
# - 若本期曾更換 engine_oil → 顯示「機油芯」「柴油芯」「機油」
# - 若本期曾更換 circulation_oil → 顯示「煞車」「排水」「進油」「回油」「循環油」
# - 其他齒輪油/皮帶 → 直接用 PART_LABELS
def _frontend_parts_labels(already_parts: set[str], already_cons: set[str]) -> list[str]:
    """
    把同週期內「已完成」的 部件＋耗材 轉為中文顯示清單。
    - 主捲、獅頭個別顯示；補捲/起伏/旋回合併為「其他」。
    - 有主件（engine_oil / circulation_oil）時：濾芯先列，再列主件。
    - 也會把「獨立記錄的耗材」補上（即使沒有主件也會顯示）。
    """
    labels: list[str] = []

    # 主捲、獅頭個別顯示
    for code in ["main_hoist_gear_oil", "lion_head_gear_oil"]:
        if code in already_parts:
            labels.append(PART_LABELS.get(code, code))

    # 補捲/起伏/旋回 → 合併為「其他」
    if any(c in already_parts for c in GROUPED_AS_OTHER):
        labels.append("其他")

    # 皮帶齒盤
    if "belts" in already_parts:
        labels.append(PART_LABELS["belts"])

    # engine_oil：濾芯先列，再列主項
    if "engine_oil" in already_parts:
        labels.extend([
            CONSUMABLE_LABELS["engine_oil_filter"],  # 機油芯
            CONSUMABLE_LABELS["fuel_oil_filter"],    # 柴油芯
            PART_LABELS["engine_oil"],               # 機油
        ])

    # circulation_oil：四個濾芯先列，再列主項
    if "circulation_oil" in already_parts:
        labels.extend([
            CONSUMABLE_LABELS["braker_drain_filter"],      # 煞車
            CONSUMABLE_LABELS["circulation_drain_filter"], # 排水
            CONSUMABLE_LABELS["circulation_inlet_filter"], # 進油
            CONSUMABLE_LABELS["circulation_return_filter"],# 回油
            PART_LABELS["circulation_oil"],                # 循環油
        ])

    # 把「獨立記錄的耗材」也補上（即使沒有主件）
    for c in [
        "engine_oil_filter",
        "fuel_oil_filter",
        "braker_drain_filter",
        "circulation_drain_filter",
        "circulation_inlet_filter",
        "circulation_return_filter",
    ]:
        if c in already_cons:
            labels.append(CONSUMABLE_LABELS.get(c, c))

    # 去重保序
    seen, ordered = set(), []
    for s in labels:
        if s not in seen:
            seen.add(s)
            ordered.append(s)
    return ordered
# =================================================================
#  GET：單一吊車維護總覽（適合你的單車 UI）
#    /api/cranes/<crane_id>/maintenance  [GET]
#    回傳：
#      - 當下週期資訊（index/start/end）
#      - 本期應更換（due_parts）
#      - 本期已更換（already_replaced）
#      - 本期未更換（pending_parts）
#      - 該車最新一筆保養紀錄（maintenance）供 UI 顯示

#  POST：在該吊車底下新增保養紀錄（支援中文/英文/混用）
#    /api/cranes/<crane_id>/maintenance  [POST]
# =================================================================
@api_ns.route("/api/cranes/<int:crane_id>/maintenance", methods=["GET", "POST"])
class CraneMaintenanceCreate(Resource):

    @jwt_required()
    @handle_request_exception
    def get(self, crane_id: int):
        # 先確認車存在 & 算一次總時數（可順便維護 usages 快取）
        total_hours = _sum_usage_hours(crane_id)
        if total_hours is None:
            return {"error": f"找不到吊車 id={crane_id}"}, 404

        # 取「該車所有保養紀錄」(新→舊)
        records = (
            MaintenanceRecord.query
            .filter(MaintenanceRecord.crane_id == crane_id)
            .order_by(MaintenanceRecord.record_date.desc(),
                      MaintenanceRecord.id.desc())
            .all()
        )

        # 先把「同車＋同週期」已更換零件聚合，供後面算 pending 用
        # key = (cycle_start, cycle_end, cycle_index)
        cycle_bucket_parts: dict[tuple[int,int,int], set] = {}
        cycle_bucket_cons : dict[tuple[int,int,int], set] = {}   # ← 新增：耗材
        cycle_info_cache: dict[int, dict] = {}

        for r in records:
            info = _cycle_info(int(r.maintenance_hours))
            cycle_info_cache[r.id] = info
            key = (info["cycle_start"], info["cycle_end"], info["cycle_index"])
            cycle_bucket_parts.setdefault(key, set()).update(r.parts or [])
            cycle_bucket_cons.setdefault(key, set()).update(r.consumables or []) 

        # 輸出清單
        result = []
        for r in records:
            info = cycle_info_cache[r.id]
            key = (info["cycle_start"], info["cycle_end"], info["cycle_index"])

            already_parts = cycle_bucket_parts.get(key, set())
            already_cons  = cycle_bucket_cons.get(key, set())     # ← 新增

            # 本期應更換的「部件」
            due_parts = set(_due_parts_for_cycle(info["cycle_index"]))
            # 由應更換部件推導本期「應更換的耗材」
            due_cons  = set(_consumables_hints_for_parts(sorted(due_parts)))  # ← 新增

            # 未更換：部件＆耗材各自算
            pending_part_codes = [c for c in sorted(due_parts) if c not in already_parts]
            pending_cons_codes = [c for c in sorted(due_cons)  if c not in already_cons]   

            # 轉中文：部件用 PART_LABELS、耗材用 CONSUMABLE_LABELS
            pending_labels = (
                [PART_LABELS.get(c, c) for c in pending_part_codes] +
                [CONSUMABLE_LABELS.get(c, c) for c in pending_cons_codes]              
            )
            already_labels = _frontend_parts_labels(already_parts, already_cons)



            result.append({
                "id": r.id,
                "crane_id": r.crane_id,
                "date": r.record_date.isoformat(),
                "maintain_hour": r.maintenance_hours,
                "cycle": info["cycle_index"],
                "parts": already_labels, # 仍保留你現有的「中文＋濾芯展開」
                "pending_parts": pending_labels,                  # ← 現在會包含「排水／進油／回油」
            })

        return {"status": "0", "result": result}, 200

    @jwt_required()
    @handle_request_exception
    def post(self, crane_id: int):
        data = request.get_json(silent=True) or {}

        maintenance_hours = data.get("maintenance_hours")
        date_str = data.get("date")
        parts_in = data.get("parts") or []
        consumables_in = data.get("consumables") or []
        note = data.get("note")

        user = User.query.get(get_jwt_identity())
        if not user:
            return {"status": 1, "result": "使用者不存在"}, 403

        if maintenance_hours is None or not date_str:
            return {"error": "必填欄位：maintenance_hours、date"}, 400

        crane = Crane.query.get(crane_id)
        if not crane:
            return {"error": f"找不到吊車 id={crane_id}"}, 404
        try:
            record_date = date.fromisoformat(date_str)
        except Exception:
            return {"error": "date 格式需為 YYYY-MM-DD"}, 400

        # 將中文/英文混用的輸入轉成代碼
        part_codes, bad_parts = _normalize_part_codes(parts_in)
        if bad_parts:
            return {"error": f"parts 包含未知名稱/代碼: {bad_parts}"}, 400

        cons_codes, bad_cons = _normalize_consumable_codes(consumables_in)
        if bad_cons:
            return {"error": f"consumables 包含未知名稱/代碼: {bad_cons}"}, 400

        # 以「保養時數」所屬週期做重複檢查（同吊車、同週期避免重複更換）
        info = _cycle_info(int(maintenance_hours))
        existing = (
            MaintenanceRecord.query
            .filter(
                MaintenanceRecord.crane_id == crane_id,
                MaintenanceRecord.maintenance_hours >= info["cycle_start"],
                MaintenanceRecord.maintenance_hours <  info["cycle_end"],
            ).all()
        )
        replaced_codes = set()
        for r in existing:
            if r.parts:
                replaced_codes.update(r.parts)

        # 本次要新增但已在該週期做過的 → 視為跳過
        new_part_codes = [p for p in part_codes if p not in replaced_codes]
        skipped_codes = [p for p in part_codes if p in replaced_codes]

        if not new_part_codes and part_codes:
            return {
                "statue":1,
                "result": "該週期內此吊車的這些零件已更換過",
                "skipped_parts": _code_label_list(skipped_codes, "part"),
                "cycle": info["cycle_index"]
            }, 409

        # 若你希望「未傳 consumables」但有包含需濾心的油品，自動補齊耗材：
        if not cons_codes:
            # 依「實際要換的零件」推耗材
            auto_cons = _consumables_hints_for_parts(new_part_codes or part_codes)
            cons_codes = list(dict.fromkeys(cons_codes + auto_cons))

        record = MaintenanceRecord(
            crane_id=crane_id,
            record_date=record_date,
            maintenance_hours=int(maintenance_hours),
            parts=new_part_codes or part_codes,
            consumables=(cons_codes or None),      
            note=note,
            created_by=user.id
        )
        db.session.add(record)

        # ── 登記保養後直接進入下一個週期 ──
        # 累計工時推進到下一週期起點（例如 0~500hr 中途保養 → 跳到 500hr 進入第 2 週期）。
        # 僅當本次保養時數落在「當前週期」內才跳，補登過往週期的紀錄不影響現況。
        cycle_jump = None
        total_now = _sum_usage_hours(crane_id)
        info_now = _cycle_info(int(total_now), crane_id)
        if info_now["cycle_start"] <= int(maintenance_hours) < info_now["cycle_end"]:
            target_total = float(info_now["cycle_end"])
            delta = target_total - float(total_now)
            if delta > 0:
                daily_work = db.session.query(
                    func.coalesce(func.sum(DailyTask.work_time), 0.0)
                ).filter(
                    DailyTask.crane_id == crane_id,
                    DailyTask.is_deleted.is_(False)
                ).scalar() or 0.0
                crane.initial_hours = int(max(0.0, target_total - float(daily_work)))

                # 板真鋼索基準同步墊高：跳週期灌入的虛擬時數不得計入鋼索使用時數，
                # 否則輪式 450hr 門檻會被跳出來的時數提早觸發換索警報。
                wr = CraneWireRope.query.filter_by(crane_id=crane_id).first()
                if wr is None:
                    wr = CraneWireRope(crane_id=crane_id)
                    db.session.add(wr)
                wr.last_replaced_hours = float(wr.last_replaced_hours or 0.0) + delta
                db.session.flush()

            new_total = _sum_usage_hours(crane_id)
            new_info = _cycle_info(int(new_total), crane_id)
            cycle_jump = {
                "previous_cycle": info_now["cycle_index"],
                "current_cycle":  new_info["cycle_index"],
                "cycle_start":    new_info["cycle_start"],
                "cycle_end":      new_info["cycle_end"],
                "total_hours":    new_total,
            }

        db.session.commit()

        if cycle_jump:
            _sync_usage_hours_cache(crane_id)
            logger.info(
                f"Maintenance cycle jump: crane={crane_id} "
                f"cycle {cycle_jump['previous_cycle']} → {cycle_jump['current_cycle']} "
                f"(total_hours={cycle_jump['total_hours']})"
            )

        return {
                "status": "0",
                "record": {
                    "id": record.id,
                    "crane_id": record.crane_id,
                    "record_date": record.record_date.isoformat(),
                    "maintenance_hours": record.maintenance_hours,
                    "parts": record.parts or [],
                    "consumables": [CONSUMABLE_LABELS.get(c, c) for c in (record.consumables or [])],
                    "note": record.note,
                },
                "cycle_jump": cycle_jump,
            }, 200



# 新增：單筆保養紀錄 GET
@api_ns.route("/api/maintenance/records/<int:record_id>", methods=["GET"])
class MaintenanceRecordGet(Resource):

    @jwt_required()
    @handle_request_exception
    def get(self, record_id: int):
        r: MaintenanceRecord | None = MaintenanceRecord.query.get(record_id)
        if not r:
            return {"status": "1", "result": f"找不到保養紀錄 id={record_id}"}, 404

        # 以該筆 maintenance_hours 算週期
        info = _cycle_info(int(r.maintenance_hours))
        key_start, key_end, idx = info["cycle_start"], info["cycle_end"], info["cycle_index"]

        # 同吊車、同週期內已經做過的「部件」＆「耗材」
        same_cycle_records = (
            MaintenanceRecord.query
            .filter(
                MaintenanceRecord.crane_id == r.crane_id,
                MaintenanceRecord.maintenance_hours >= key_start,
                MaintenanceRecord.maintenance_hours <  key_end,
            ).all()
        )
        already_parts, already_cons = set(), set()
        for x in same_cycle_records:
            if x.parts:       already_parts.update(x.parts)
            if x.consumables: already_cons.update(x.consumables)

        # 本期應更換部件 & 由部件推導應更換耗材
        due_parts = set(_due_parts_for_cycle(idx))
        due_cons  = set(_consumables_hints_for_parts(sorted(due_parts)))

        # 未更換：部件＋耗材
        pending_part_codes = [c for c in sorted(due_parts) if c not in already_parts]
        pending_cons_codes = [c for c in sorted(due_cons)  if c not in already_cons]

        # 轉中文
        pending_labels = (
            [PART_LABELS.get(c, c) for c in pending_part_codes] +
            [CONSUMABLE_LABELS.get(c, c) for c in pending_cons_codes]
        )

        # 回傳（與列表元素一致）
        result = {
            "id": r.id,
            "crane_id": r.crane_id,
            "date": r.record_date.isoformat(),
            "maintain_hour": r.maintenance_hours,
            "cycle": idx,
            # 這裡會呼叫到「全域版」_frontend_parts_labels(already_parts, already_cons)
            "parts": _frontend_parts_labels(already_parts, already_cons),
            "pending_parts": pending_labels,
        }
        return {"status": "0", "result": [result]}, 200


# =================================================================
#  PUT：更新單筆保養紀錄
#    /api/maintenance/records/<record_id>  [PUT]
#    Body 欄位（皆選填）：date, maintenance_hours, parts, consumables, note
#    parts/consumables 可傳中文或代碼；若未傳 consumables 且包含需濾心油品，會自動補齊
# =================================================================
@api_ns.route("/api/maintenance/records/<int:record_id>", methods=["PUT"])
class MaintenanceRecordUpdate(Resource):

    @jwt_required()
    @handle_request_exception
    def put(self, record_id: int):
        data = request.get_json(silent=True) or {}

        r: MaintenanceRecord | None = MaintenanceRecord.query.get(record_id)
        if not r:
            return {"error": f"找不到保養紀錄 id={record_id}"}, 404

        # 允許更新的欄位
        date_str = data.get("date")
        maintenance_hours = data.get("maintenance_hours")
        parts_in = data.get("parts")
        consumables_in = data.get("consumables")
        note = data.get("note")

        # 日期
        if date_str is not None:
            try:
                r.record_date = date.fromisoformat(date_str)
            except Exception:
                return {"error": "date 格式需為 YYYY-MM-DD"}, 400

        # 保養時數
        if maintenance_hours is not None:
            try:
                r.maintenance_hours = int(maintenance_hours)
            except Exception:
                return {"error": "maintenance_hours 需為整數小時數"}, 400

        # parts / consumables 正規化
        if parts_in is not None:
            part_codes, bad_parts = _normalize_part_codes(parts_in or [])
            if bad_parts:
                return {"error": f"parts 包含未知名稱/代碼: {bad_parts}"}, 400
        else:
            part_codes = r.parts or []

        if consumables_in is not None:
            cons_codes, bad_cons = _normalize_consumable_codes(consumables_in or [])
            if bad_cons:
                return {"error": f"consumables 包含未知名稱/代碼: {bad_cons}"}, 400
        else:
            cons_codes = r.consumables or []

        # 週期 & 同週期避免重複更換：計算要寫入的 new_part_codes 與回報用 skipped_codes
        hours_for_cycle = int(r.maintenance_hours)
        if maintenance_hours is not None:
            hours_for_cycle = int(maintenance_hours)

        info = _cycle_info(hours_for_cycle)
        existing = (
            MaintenanceRecord.query
            .filter(
                MaintenanceRecord.crane_id == r.crane_id,
                MaintenanceRecord.id != r.id,  # 排除自己
                MaintenanceRecord.maintenance_hours >= info["cycle_start"],
                MaintenanceRecord.maintenance_hours <  info["cycle_end"],
            ).all()
        )
        replaced_codes = set()
        for e in existing:
            if e.parts:
                replaced_codes.update(e.parts)

        new_part_codes = [p for p in part_codes if p not in replaced_codes]
        # parts_in 可能是 None，為避免未定義，這裡保證 skipped_codes 一定存在
        skipped_codes = [p for p in (parts_in or []) if p in replaced_codes] if parts_in is not None else []

        # 若未傳 consumables，依「實際要換的零件」自動補（包含你剛剛過濾後的 new_part_codes）
        if consumables_in is None:
            auto_cons = _consumables_hints_for_parts(new_part_codes or part_codes)
            # 舊資料 + 自動補的去重
            cons_codes = list(dict.fromkeys((r.consumables or []) + auto_cons))

        # 寫入 DB
        r.parts = new_part_codes or part_codes
        r.consumables = cons_codes or None
        if note is not None:
            r.note = note

        db.session.commit()

        # 重新以這筆紀錄的 hours 計算週期，並聚合同週期的「已完成部件＆耗材」
        info = _cycle_info(int(r.maintenance_hours))
        same_cycle_records = (
            MaintenanceRecord.query
            .filter(
                MaintenanceRecord.crane_id == r.crane_id,
                MaintenanceRecord.maintenance_hours >= info["cycle_start"],
                MaintenanceRecord.maintenance_hours <  info["cycle_end"],
            ).all()
        )
        already_parts, already_cons = set(), set()
        for x in same_cycle_records:
            if x.parts:       already_parts.update(x.parts)
            if x.consumables: already_cons.update(x.consumables)

        result = {
            "id": r.id,  # 若前端要車 id 改成 r.crane_id
            "date": r.record_date.isoformat(),
            "maintain_hour": r.maintenance_hours,
            # parts = 同週期聚合（含獨立耗材；油品則濾芯先列、主件後列）
            "parts": _frontend_parts_labels(already_parts, already_cons),
        }
        return {
            "status": "0",
            "result": result,
            "cycle": info["cycle_index"],
            "skipped_parts": _code_label_list(skipped_codes, "part"),
            "record": r.to_dict(),
            "record_humanized": {
                "parts": _code_label_list(r.parts or [], "part"),
                "consumables": _code_label_list(r.consumables or [], "consumable"),
            },
        }, 200

# =================================================================
#  DELETE：刪除單筆保養紀錄（硬刪；你的模型沒有 is_deleted）
#    /api/maintenance/records/<record_id>  [DELETE]
# =================================================================
@api_ns.route("/api/maintenance/records/<int:record_id>", methods=["DELETE"])
class MaintenanceRecordDelete(Resource):

    @jwt_required()
    @handle_request_exception
    def delete(self, record_id: int):
        r: MaintenanceRecord | None = MaintenanceRecord.query.get(record_id)
        if not r:
            return {"error": f"找不到保養紀錄 id={record_id}"}, 404

        db.session.delete(r)
        db.session.commit()
        return {"status": "0", "result": "保養紀錄已成功刪除"}, 200


# =================================================================
#  GET：查該吊車「當下週期」需更換
#    /api/cranes/<crane_id>/maintenance/due  [GET]
# =================================================================
@api_ns.route("/api/cranes/<int:crane_id>/maintenance/due", methods=["GET"])
class CraneMaintenanceDue(Resource):

    @jwt_required()
    @handle_request_exception
    def get(self, crane_id: int):
        total_hours = _sum_usage_hours(crane_id)
        if total_hours is None:
            return {"error": f"找不到吊車 id={crane_id}"}, 404

        crane = Crane.query.get(crane_id)
        info = _cycle_info(total_hours, crane_id)          # 使用 DB 狀態
        due_codes: list[str] = _due_parts_for_cycle(info["cycle_index"])       # 本期應更換「部件」代碼
        due_set = set(due_codes)

        # 根據 due 的部件，推導本期需提示的「耗材」清單（純提示，與是否已換無關）
        hint_codes: list[str] = _consumables_hints_for_parts(due_codes)

        # 取該吊車在「本期週期」內的所有保養紀錄
        records = (
            MaintenanceRecord.query
            .filter(
                MaintenanceRecord.crane_id == crane_id,
                MaintenanceRecord.maintenance_hours >= info["cycle_start"],
                MaintenanceRecord.maintenance_hours <  info["cycle_end"],
            ).all()
        )

        # —— 已更換：只統計「本期 due 的部件」；同時納入：1) 紀錄直接寫的耗材 2) 由已更換部件推到的耗材 ——
        already_part_codes: set[str] = set()
        already_cons_codes: set[str] = set()

        for r in records:
            # parts：本次紀錄中實際寫入的部件
            for code in (r.parts or []):
                if code in ALLOWED_PARTS and code in due_set:
                    already_part_codes.add(code)
                    # 由該部件推導對應耗材（即使紀錄沒單獨寫，也視同一起完成）
                    already_cons_codes.update(CONSUMABLES_HINTS.get(code, []))

            # consumables：若紀錄本身就有寫耗材，一併納入
            for c in (r.consumables or []):
                if c in ALLOWED_CONSUMABLES:
                    already_cons_codes.add(c)

        # 待更換（僅部件）：本期 due 的部件中尚未在 already_part_codes 的
        pending_part_codes = [p for p in due_codes if p not in already_part_codes]

        # —— 輸出成中文（已更換要把「部件＋耗材」一起回傳）——
        already_labels = (
            _code_label_list(sorted(already_part_codes), "part") +
            _code_label_list(sorted(already_cons_codes),  "consumable")
        )

        # 板真鋼索狀態（依小時計算）
        wire_rope   = CraneWireRope.query.filter_by(crane_id=crane_id).first()
        wr_threshold = WIRE_ROPE_THRESHOLD[bool(crane.crane_type)]
        wr_base      = float(wire_rope.last_replaced_hours) if (wire_rope and wire_rope.last_replaced_hours is not None) else 0.0
        wr_since     = round(float(total_hours) - wr_base, 1)

        return {
            "crane_id": crane_id,
            "total_hours": total_hours,
            "cycle": info["cycle_index"],   # 1..12
            "cycle_start": info["cycle_start"],
            "cycle_end":   info["cycle_end"],
            "needs_maintenance_alert": _maintenance_alert(crane, total_hours, info),
            "due_parts": _code_label_list(due_codes, "part"),
            "consumables_hint": _code_label_list(hint_codes, "consumable"),
            "already_replaced": already_labels,
            "pending_parts": _code_label_list(pending_part_codes, "part"),
            "wire_rope": {
                "needs_replacement":       wr_since >= wr_threshold,
                "replacement_count":       wire_rope.replacement_count if wire_rope else 0,
                "last_replaced_hours":     wire_rope.last_replaced_hours if wire_rope else None,
                "hours_since_replacement": wr_since,
                "threshold":               wr_threshold,
            },
        }, 200


# =================================================================
#  後台管理：保養週期狀態
#  GET  /api/cranes/<id>/maintenance/state   → 查看當前週期狀態
#  PUT  /api/cranes/<id>/maintenance/state   → 調整到指定週期（需 permission>=2）
#  POST /api/cranes/<id>/maintenance/state/reset → 重置至第 1 週期（需 permission>=2）
# =================================================================
@api_ns.route("/api/cranes/<int:crane_id>/maintenance/state", methods=["GET", "PUT"])
class CraneMaintenanceStateResource(Resource):

    @jwt_required()
    @handle_request_exception
    def get(self, crane_id: int):
        """查看吊車保養週期狀態（後台）"""
        total_hours = _sum_usage_hours(crane_id)
        if total_hours is None:
            return {"error": f"找不到吊車 id={crane_id}"}, 404

        crane = Crane.query.get(crane_id)
        info  = _cycle_info(total_hours, crane_id)
        state = CraneMaintenanceState.query.filter_by(crane_id=crane_id).first()

        return {
            "status": "0",
            "result": {
                "crane_id":               crane_id,
                "total_hours":            total_hours,
                "current_cycle":          info["cycle_index"],
                "cycle_start":            info["cycle_start"],
                "cycle_end":              info["cycle_end"],
                "round_base_hours":       info["round_base"],
                "initial_cycle":          state.initial_cycle  if state else 1,
                "reset_count":            state.reset_count    if state else 0,
                "last_reset_at":          state.last_reset_at.isoformat() if state and state.last_reset_at else None,
                "needs_maintenance_alert": _maintenance_alert(crane, total_hours, info),
            }
        }, 200

    @jwt_required()
    @handle_request_exception
    def put(self, crane_id: int):
        """調整吊車保養至指定週期（需 permission >= 2）
        Body: { "target_cycle": 3 }
        - 累計工時自動調整至該週期的最小值：(target_cycle - 1) × 500 hr
        - 過往未保養項目一律無視，從調整後的時數重新計算
        """
        user = User.query.get(get_jwt_identity())
        if not user or user.permission < 2:
            return {"error": "需要管理者權限 (permission >= 2)"}, 403

        data = request.get_json(silent=True) or {}
        target_cycle = data.get("target_cycle")
        if target_cycle is None:
            return {"error": "必填欄位：target_cycle (1~12)"}, 400
        try:
            target_cycle = int(target_cycle)
        except (ValueError, TypeError):
            return {"error": "target_cycle 需為整數"}, 400
        if not (1 <= target_cycle <= CYCLES_PER_ROUND):
            return {"error": f"target_cycle 需介於 1~{CYCLES_PER_ROUND}"}, 400

        crane = Crane.query.get(crane_id)
        if crane is None:
            return {"error": f"找不到吊車 id={crane_id}"}, 404

        # ── 將累計工時調整至該週期最小值 ──
        target_total = float((target_cycle - 1) * CYCLE_HOURS)

        daily_work = db.session.query(
            func.coalesce(func.sum(DailyTask.work_time), 0.0)
        ).filter(
            DailyTask.crane_id == crane_id,
            DailyTask.is_deleted.is_(False)
        ).scalar() or 0.0

        # initial_hours = 目標總時數 - 已記錄 DailyTask 工時（最低 0）
        crane.initial_hours = int(max(0.0, target_total - float(daily_work)))
        db.session.flush()  # 讓 _sum_usage_hours 讀到更新後的值

        total_hours = _sum_usage_hours(crane_id)

        # round_base = total - (target-1)*500
        # 若 daily_work > target_total，total_hours > target_total，
        # new_base 可能為負，但 _cycle_info 仍能正確計算，
        # 且 cycle_start == target_total，過往紀錄自然落在範圍外。
        new_base = int(total_hours) - (target_cycle - 1) * CYCLE_HOURS

        state = CraneMaintenanceState.query.filter_by(crane_id=crane_id).first()
        if state is None:
            state = CraneMaintenanceState(crane_id=crane_id)
            db.session.add(state)

        state.round_base_hours = float(new_base)
        state.initial_cycle    = target_cycle
        state.reset_count     += 1
        state.last_reset_at    = datetime.datetime.now(tz)
        state.last_reset_by    = user.id
        db.session.commit()

        info = _cycle_info(total_hours, crane_id)
        return {
            "status": "0",
            "result": {
                "crane_id":         crane_id,
                "current_cycle":    info["cycle_index"],
                "total_hours":      total_hours,
                "round_base_hours": state.round_base_hours,
                "initial_cycle":    state.initial_cycle,
                "reset_count":      state.reset_count,
            }
        }, 200


@api_ns.route("/api/cranes/<int:crane_id>/maintenance/state/reset", methods=["POST"])
class CraneMaintenanceStateReset(Resource):

    @jwt_required()
    @handle_request_exception
    def post(self, crane_id: int):
        """重置保養週期至第 1 週期（需 permission >= 2）"""
        user = User.query.get(get_jwt_identity())
        if not user or user.permission < 2:
            return {"error": "需要管理者權限 (permission >= 2)"}, 403

        total_hours = _sum_usage_hours(crane_id)
        if total_hours is None:
            return {"error": f"找不到吊車 id={crane_id}"}, 404

        state = CraneMaintenanceState.query.filter_by(crane_id=crane_id).first()
        if state is None:
            state = CraneMaintenanceState(crane_id=crane_id)
            db.session.add(state)

        state.round_base_hours = float(int(total_hours))
        state.initial_cycle    = 1
        state.reset_count     += 1
        state.last_reset_at    = datetime.datetime.now(tz)
        state.last_reset_by    = user.id
        db.session.commit()

        return {
            "status": "0",
            "result": {
                "crane_id":        crane_id,
                "current_cycle":   1,
                "round_base_hours": state.round_base_hours,
                "reset_count":     state.reset_count,
                "message":         "保養週期已重置至第 1 週期",
            }
        }, 200


# =================================================================
#  鋼索保養管理
#  GET  /api/cranes/<id>/wire-rope          → 查看鋼索狀態
#  PUT  /api/cranes/<id>/wire-rope          → 後台手動設定狀態（需 permission>=2）
#  POST /api/cranes/<id>/wire-rope/reset    → 老闆更換鋼索後手動重置
# =================================================================
@api_ns.route("/api/cranes/<int:crane_id>/wire-rope", methods=["GET", "PUT"])
class CraneWireRopeResource(Resource):

    @jwt_required()
    @handle_request_exception
    def get(self, crane_id: int):
        """查看吊車鋼索狀態"""
        crane = Crane.query.get(crane_id)
        if not crane:
            return {"error": f"找不到吊車 id={crane_id}"}, 404

        wr = CraneWireRope.query.filter_by(crane_id=crane_id).first()
        if wr is None:
            wr = CraneWireRope(crane_id=crane_id)
            db.session.add(wr)
            db.session.commit()

        total_hours = _sum_usage_hours(crane_id) or float(crane.initial_hours or 0)
        threshold   = WIRE_ROPE_THRESHOLD[bool(crane.crane_type)]
        base        = float(wr.last_replaced_hours) if wr.last_replaced_hours is not None else 0.0
        hours_since = round(total_hours - base, 1)

        return {
            "status": "0",
            "result": {
                "crane_id":            crane_id,
                "needs_replacement":   hours_since >= threshold,
                "replacement_count":   wr.replacement_count,
                "last_replaced_at":    wr.last_replaced_at.isoformat() if wr.last_replaced_at else None,
                "last_replaced_hours": wr.last_replaced_hours,
                "total_hours":         total_hours,
                "hours_since_replacement": hours_since,
                "threshold":           threshold,
            }
        }, 200

    @jwt_required()
    @handle_request_exception
    def put(self, crane_id: int):
        """後台設定板真鋼索初始狀態（需 permission >= 2）

        用途：車輛引入系統時，設定上次換索當時的時數與日期基準值，
        不產生更換紀錄（replacement_count 不累加）。

        Body（all optional）:
          last_replaced_hours: float   - 上次換索時的吊車總時數（初始基準）
          last_replaced_at:    string  - 上次換索日期，格式 "YYYY-MM-DD"
          note:                string  - 備註
        """
        user = User.query.get(get_jwt_identity())
        if not user or user.permission < 2:
            return {"error": "需要管理者權限 (permission >= 2)"}, 403

        crane = Crane.query.get(crane_id)
        if not crane:
            return {"error": f"找不到吊車 id={crane_id}"}, 404

        data = request.get_json(silent=True) or {}

        wr = CraneWireRope.query.filter_by(crane_id=crane_id).first()
        if wr is None:
            wr = CraneWireRope(crane_id=crane_id)
            db.session.add(wr)

        # 設定上次換索時數基準
        if "last_replaced_hours" in data:
            try:
                wr.last_replaced_hours = float(data["last_replaced_hours"])
            except (ValueError, TypeError):
                return {"error": "last_replaced_hours 需為數字"}, 400

        # 設定上次換索日期
        if "last_replaced_at" in data:
            date_str = data["last_replaced_at"]
            if date_str:
                try:
                    d = datetime.datetime.strptime(date_str, "%Y-%m-%d")
                    wr.last_replaced_at = tz.localize(d)
                except ValueError:
                    return {"error": "last_replaced_at 格式錯誤，請用 YYYY-MM-DD"}, 400
            else:
                wr.last_replaced_at = None

        wr.last_replaced_by = user.id
        db.session.commit()

        total_hours = _sum_usage_hours(crane_id) or float(crane.initial_hours or 0)
        threshold   = WIRE_ROPE_THRESHOLD[bool(crane.crane_type)]
        base        = float(wr.last_replaced_hours) if wr.last_replaced_hours is not None else 0.0
        hours_since = round(total_hours - base, 1)

        return {
            "status": "0",
            "result": {
                "crane_id":                crane_id,
                "last_replaced_hours":     wr.last_replaced_hours,
                "last_replaced_at":        wr.last_replaced_at.isoformat() if wr.last_replaced_at else None,
                "replacement_count":       wr.replacement_count,
                "hours_since_replacement": hours_since,
                "threshold":               threshold,
                "message":                 "板真鋼索初始狀態已更新",
            }
        }, 200


@api_ns.route("/api/cranes/<int:crane_id>/wire-rope/reset", methods=["POST"])
class CraneWireRopeReset(Resource):

    @jwt_required()
    @handle_request_exception
    def post(self, crane_id: int):
        """更換板真鋼索後重置計時（任意已登入使用者皆可操作）

        重置後：replacement_count+1，以指定（或當前）時數/日期為新基準。

        Body（all optional）:
          replaced_at:    string  - 實際更換日期，格式 "YYYY-MM-DD"，預設今天
          replaced_hours: float   - 更換當時吊車時數，預設目前累計時數
          note:           string  - 備註
        """
        user = User.query.get(get_jwt_identity())
        if not user:
            return {"error": "使用者不存在"}, 403

        crane = Crane.query.get(crane_id)
        if not crane:
            return {"error": f"找不到吊車 id={crane_id}"}, 404

        current_total = _sum_usage_hours(crane_id)
        if current_total is None:
            return {"error": f"找不到吊車 id={crane_id}"}, 404

        data = request.get_json(silent=True) or {}
        note = data.get("note")

        # ── 解析更換日期（可選，預設今天）──
        replaced_at_str = data.get("replaced_at")
        if replaced_at_str:
            try:
                d = datetime.datetime.strptime(replaced_at_str, "%Y-%m-%d")
                replaced_at = tz.localize(d)
            except ValueError:
                return {"error": "replaced_at 格式錯誤，請用 YYYY-MM-DD"}, 400
        else:
            replaced_at = datetime.datetime.now(tz)

        # ── 解析更換時數（可選，預設目前累計時數）──
        replaced_hours_raw = data.get("replaced_hours")
        if replaced_hours_raw is not None:
            try:
                replaced_hours = float(replaced_hours_raw)
            except (ValueError, TypeError):
                return {"error": "replaced_hours 需為數字"}, 400
        else:
            replaced_hours = float(current_total)

        wr = CraneWireRope.query.filter_by(crane_id=crane_id).first()
        if wr is None:
            wr = CraneWireRope(crane_id=crane_id)
            db.session.add(wr)

        wr.needs_replacement   = False
        wr.replacement_count  += 1
        wr.last_replaced_at    = replaced_at
        wr.last_replaced_hours = replaced_hours
        wr.last_replaced_by    = user.id

        # 寫入更換歷程
        log = CraneWireRopeLog(
            crane_id       = crane_id,
            replaced_at    = replaced_at,
            replaced_hours = replaced_hours,
            replaced_by    = user.id,
            note           = note,
        )
        db.session.add(log)
        db.session.commit()

        threshold = WIRE_ROPE_THRESHOLD[bool(crane.crane_type)]

        return {
            "status": "0",
            "result": {
                "crane_id":            crane_id,
                "needs_replacement":   False,
                "replacement_count":   wr.replacement_count,
                "last_replaced_at":    replaced_at.strftime("%Y-%m-%d"),
                "last_replaced_hours": wr.last_replaced_hours,
                "threshold":           threshold,
                "message":             "板真鋼索已標記為更換完成，計時重置",
            }
        }, 200


# =================================================================
#  板真鋼索更換歷程
#  GET /api/cranes/<id>/wire-rope/logs  → 查詢所有更換紀錄
# =================================================================
@api_ns.route("/api/cranes/<int:crane_id>/wire-rope/logs", methods=["GET"])
class CraneWireRopeLogs(Resource):

    @jwt_required()
    @handle_request_exception
    def get(self, crane_id: int):
        """查詢板真鋼索更換歷程（所有已登入使用者可查看）"""
        crane = Crane.query.get(crane_id)
        if not crane:
            return {"error": f"找不到吊車 id={crane_id}"}, 404

        logs = (
            CraneWireRopeLog.query
            .filter_by(crane_id=crane_id)
            .order_by(CraneWireRopeLog.replaced_at.desc())
            .all()
        )

        return {
            "status": "0",
            "result": [
                {
                    "id":             log.id,
                    "crane_id":       log.crane_id,
                    "replaced_at":    log.replaced_at.isoformat(),
                    "replaced_hours": log.replaced_hours,
                    "replaced_by":    log.replaced_by,
                    "note":           log.note,
                }
                for log in logs
            ]
        }, 200
