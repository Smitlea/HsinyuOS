# export_routes.py
from __future__ import annotations
import io
import datetime as dt
from collections import defaultdict

import pytz
import pandas as pd
from flask import Blueprint, request, send_file
from sqlalchemy import and_, extract
from sqlalchemy.orm import joinedload

from static.payload import api
from flask_restx import Resource
from static.models import (
    db, User, ConstructionSite, Crane, DailyTask, TaskMaintenance,
    WorkRecord, Truck, OilDrumRecord, TruckFuelRecord,
    CraneMaintenance, MaintenanceRecord,
    _due_parts_for_cycle, CYCLE_HOURS, ROUND_HOURS
)

tz = pytz.timezone("Asia/Taipei")

# ---------- 共用：年份解析 ----------
def _parse_year():
    y = request.args.get("year", type=int)
    if not y:
        y = dt.datetime.now(tz).year
    start = dt.datetime(y, 1, 1, tzinfo=tz).date()
    end   = dt.datetime(y, 12, 31, tzinfo=tz).date()
    return y, start, end

# ---------- 共用：Excel 輸出 ----------
def _send_df_as_excel(df: pd.DataFrame, filename: str, sheet_name: str,
                      header_style=None, build_two_level_header: callable | None = None):
    output = io.BytesIO()
    # 用 xlsxwriter 才能做合併儲存格
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        # 先寫入，等下再套格式
        df.to_excel(writer, index=False, sheet_name=sheet_name, startrow=1 if build_two_level_header else 0)
        ws = writer.sheets[sheet_name]
        wb = writer.book

        # 基本樣式
        fmt_header = wb.add_format({"bold": True, "align": "center", "valign": "vcenter", "border": 1})
        fmt_cell   = wb.add_format({"border": 1})
        fmt_date   = wb.add_format({"num_format": "yyyy.mm.dd", "border": 1})

        # 加框線
        nrows, ncols = df.shape
        ws.set_column(0, ncols-1, 14)  # 欄寬
        # 日期欄用日期格式（假設第一欄是日期）
        ws.set_column(0, 0, 12, fmt_date)
        if ncols > 1:
            ws.set_column(1, ncols-1, 14, fmt_cell)

        if build_two_level_header:
            # 兩層表頭（例如「貨車柴油」）
            build_two_level_header(wb, ws, fmt_header)
            # 第二列（startrow=1）是實際欄名，套用置中粗體
            for c, col in enumerate(df.columns):
                ws.write(1, c, col, fmt_header)
        else:
            # 單列表頭
            for c, col in enumerate(df.columns):
                ws.write(0, c, col, fmt_header)

    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        max_age=0
    )

# ---------- 1) 日常登記 ----------
@api.route("/api/export/daily")
class ExportDaily(Resource):
    def get(self):
        """
        欄位：日期, 廠商, 車號, 地點, 人員, 時數, 吊怪手200, 吊怪手120,
            輔助人員A, 輔助人員B, 輔助人員C, 輔助人員D, 當日保養, 備註
        來源：
        - DailyTask（工作時數、廠商、地點、備註、車號、日期）
        - WorkRecord（吊怪手200/120、輔助人員、備註），以 日期+crane_id+site_id 合併
        - TaskMaintenance（當日保養：同日同場地/同車之描述合併）
        """
        year, start, end = _parse_year()

        # 取 DailyTask 基底
        daily_rows = (
            db.session.query(DailyTask)
            .options(
                joinedload(DailyTask.crane),
                joinedload(DailyTask.site),
                joinedload(DailyTask.updater),
            )
            .filter(
                DailyTask.is_deleted.is_(False),
                and_(DailyTask.task_date >= start, DailyTask.task_date <= end)
            )
            .all()
        )

        # WorkRecord 做成查表：key=(date, crane_id, site_id)
        wr_by_key = {}
        for wr in db.session.query(WorkRecord)\
            .options(joinedload(WorkRecord.crane), joinedload(WorkRecord.site), joinedload(WorkRecord.updater))\
            .filter(
                WorkRecord.is_deleted.is_(False),
                and_(WorkRecord.record_date >= start, WorkRecord.record_date <= end)
            ).all():
            k = (wr.record_date, wr.crane_id, wr.site_id)
            wr_by_key[k] = wr

        # TaskMaintenance 當日保養：key=(date) 或 (date, site_id/crane_id)；實務上常用日期聚合
        maint_by_date = defaultdict(list)
        for tm in db.session.query(TaskMaintenance)\
            .filter(
                TaskMaintenance.is_deleted.is_(False),
                and_(TaskMaintenance.record_date >= start, TaskMaintenance.record_date <= end)
            ).all():
            maint_by_date[tm.record_date].append(tm.description.strip())

        records = []
        for d in daily_rows:
            k = (d.task_date, d.crane_id, d.site_id)
            wr = wr_by_key.get(k)

            assistants = (wr.assistants or []) if wr else []
            # 如果 assistants 是 user.id 陣列，取暱稱
            def _id_to_name(uid):
                u = db.session.get(User, uid)
                return (u.nickname or u.username) if u else None
            names = []
            for uid in assistants:
                if isinstance(uid, int):
                    names.append(_id_to_name(uid))
                else:
                    names.append(str(uid))
            # 填滿 A~D
            names = (names + [None, None, None, None])[:4]

            records.append({
                "日期": d.task_date,
                "廠商": d.vendor,
                "車號": d.crane.crane_number if d.crane else None,
                "地點": d.site.location if d.site else None,
                "人員": d.updated_by_nickname,  # 或者可改用建立者暱稱
                "時數": d.work_time,
                "吊怪手200": wr.qty_200 if wr else None,
                "吊怪手120": wr.qty_120 if wr else None,
                "輔助人員A": names[0],
                "輔助人員B": names[1],
                "輔助人員C": names[2],
                "輔助人員D": names[3],
                "當日保養": "、".join(maint_by_date.get(d.task_date, [])) or None,
                "備註": wr.note if (wr and wr.note) else d.note,
            })

        # 移除全空列、按日期排序
        df = pd.DataFrame.from_records(records)
        if not df.empty:
            df = df.dropna(how="all")
            df = df.sort_values(["日期", "車號"], kind="mergesort")
        return _send_df_as_excel(
            df, filename=f"日常登記_{year}.xlsx", sheet_name="日常登記"
        )

# ---------- 2) 貨車柴油（雙層表頭） ----------
@api.route("/api/export/truck-diesel")
class ExportTruckDiesel(Resource):
    def get(self):
        """
        欄位（兩層表頭）：
        第1列：日期, 貨車車號, [油桶](合併3格), , , [貨車](合併2格), 
        第2列：      ,        , 入油(L), 單價, 出油(L), 加油車號, 入油, 單價
        來源：
        - OilDrumRecord：IN → (入油(L), 單價)；OUT → (出油(L), 加油車號=crane_number)
        - TruckFuelRecord：貨車 (入油, 單價)
        """
        year, start, end = _parse_year()

        # 預先載入 truck id->number
        trucks = {t.id: t.truck_number for t in db.session.query(Truck).all()}

        rows = []

        # 油桶 IN/OUT
        for r in db.session.query(OilDrumRecord)\
            .filter(
                OilDrumRecord.is_deleted.is_(False),
                and_(OilDrumRecord.record_date >= start, OilDrumRecord.record_date <= end)
            ).order_by(OilDrumRecord.record_date.asc(), OilDrumRecord.truck_id.asc()).all():
            base = {
                "日期": r.record_date,
                "貨車車號": trucks.get(r.truck_id),
                "入油(L)": None, "單價(油桶)": None, "出油(L)": None, "加油車號": None,
                "貨車入油": None, "貨車單價": None,
            }
            if r.io_type == "IN":
                base["入油(L)"] = float(r.quantity)
                base["單價(油桶)"] = float(r.unit_price) if r.unit_price is not None else None
            else:  # OUT
                base["出油(L)"] = float(r.quantity)
                base["加油車號"] = r.crane_number
            rows.append(base)

        # 貨車自加油
        for r in db.session.query(TruckFuelRecord)\
            .filter(
                TruckFuelRecord.is_deleted.is_(False),
                and_(TruckFuelRecord.record_date >= start, TruckFuelRecord.record_date <= end)
            ).order_by(TruckFuelRecord.record_date.asc(), TruckFuelRecord.truck_id.asc()).all():
            rows.append({
                "日期": r.record_date,
                "貨車車號": trucks.get(r.truck_id),
                "入油(L)": None, "單價(油桶)": None, "出油(L)": None, "加油車號": None,
                "貨車入油": float(r.quantity), "貨車單價": float(r.unit_price)
            })

        df = pd.DataFrame.from_records(rows)
        if not df.empty:
            df = df.dropna(how="all")
            df = df.sort_values(["日期", "貨車車號"], kind="mergesort")

            # 欄位順序 & 標題，第二列要長這樣
            df = df[["日期", "貨車車號", "入油(L)", "單價(油桶)", "出油(L)", "加油車號", "貨車入油", "貨車單價"]]
            df.columns = ["日期", "貨車車號", "入油(L)", "單價", "出油(L)", "加油車號", "入油", "單價"]

        def _two_level_header(wb, ws, fmt_header):
            # 合併儲存格：A1:A2、B1:B2、C1:E1（油桶）、F1:G1（貨車）
            ws.merge_range(0, 0, 1, 0, "日期", fmt_header)
            ws.merge_range(0, 1, 1, 1, "貨車車號", fmt_header)
            ws.merge_range(0, 2, 0, 5, "油桶", fmt_header)   # C~F
            ws.merge_range(0, 6, 0, 7, "貨車", fmt_header)   # G~H

        return _send_df_as_excel(
            df, filename=f"貨車柴油_{year}.xlsx", sheet_name="貨車柴油",
            build_two_level_header=_two_level_header
        )

# ---------- 3) 維修紀錄 ----------
@api.route("/api/export/repair")
class ExportRepair(Resource):
    def get(self):
        """
        欄位：日期, 車號, 維修廠商, 維修費用, 零件, 零件廠商, 零件費用, 備註
        來源：CraneMaintenance
        對應：
        日期=maintenance_date
        車號=crane.crane_number
        維修廠商=vendor
        維修費用=vendor_cost
        零件=material
        零件廠商=parts_vendor
        零件費用=parts_cost
        備註=note
        """
        year, start, end = _parse_year()
        rows = []
        q = (db.session.query(CraneMaintenance)
            .options(joinedload(CraneMaintenance.crane))
            .filter(
                CraneMaintenance.is_deleted.is_(False),
                and_(CraneMaintenance.maintenance_date >= start, CraneMaintenance.maintenance_date <= end)
            ).order_by(CraneMaintenance.maintenance_date.asc(), CraneMaintenance.crane_id.asc()))
        for r in q.all():
            rows.append({
                "日期": r.maintenance_date,
                "車號": r.crane.crane_number if r.crane else None,
                "維修廠商": r.vendor,
                "維修費用": float(r.vendor_cost) if r.vendor_cost is not None else None,
                "零件": r.material,
                "零件廠商": r.parts_vendor,
                "零件費用": float(r.parts_cost) if r.parts_cost is not None else None,
                "備註": r.note
            })
        df = pd.DataFrame.from_records(rows)
        if not df.empty:
            df = df.dropna(how="all").sort_values(["日期", "車號"], kind="mergesort")
        return _send_df_as_excel(df, filename=f"維修紀錄_{year}.xlsx", sheet_name="維修紀錄")

# ---------- 4) 保養紀錄 ----------
def _cycle_from_hours(hours: int) -> int:
    # 依你現有規則：每 500 小時一個週期
    offset = hours % ROUND_HOURS
    cycle_index = (offset // CYCLE_HOURS) + 1  # 1..12
    return int(cycle_index)

@api.route("/api/export/maintenance")
class ExportMaintenance(Resource):
    def get(self):
        """
        欄位：日期, 車號, 上次保養時數, 本次保養時數, 實際保養時數, 保養內容, 應保養而未保養, 備註
        來源：MaintenanceRecord
        - 上次保養時數：同一車號上一筆 record 的 maintenance_hours（找不到則為 None/0）
        - 實際保養時數：本次 - 上次
        - 保養內容：parts 陣列以「、」串接
        - 應保養而未保養：由本次 hours 推算 cycle 的應保養清單，扣掉已保養 parts
        """
        year, start, end = _parse_year()

        # 先把同車號所有紀錄拉出，方便找上一筆
        q = (db.session.query(MaintenanceRecord)
            .options(joinedload(MaintenanceRecord.crane))
            .filter(
                and_(MaintenanceRecord.record_date >= start, MaintenanceRecord.record_date <= end)
            )
            .order_by(MaintenanceRecord.crane_id.asc(),
                    MaintenanceRecord.maintenance_hours.asc(),
                    MaintenanceRecord.record_date.asc()))

        rows = []
        # 需要同車號上一筆的「時數」，所以先做按 crane 分組
        by_crane: dict[int, list[MaintenanceRecord]] = defaultdict(list)
        for r in q.all():
            by_crane[r.crane_id].append(r)

        for cid, items in by_crane.items():
            prev_hours = None
            for r in items:
                curr = r.maintenance_hours
                # cycle 的應保養
                cycle = _cycle_from_hours(curr)
                due_parts = set(_due_parts_for_cycle(cycle))
                done_parts = set(r.parts or [])
                missing = sorted(list(due_parts - done_parts))

                delta = curr - (prev_hours if prev_hours is not None else curr)
                rows.append({
                    "日期": r.record_date,
                    "車號": r.crane.crane_number if r.crane else None,
                    "上次保養時數": prev_hours,
                    "本次保養時數": curr,
                    "實際保養時數": delta,
                    "保養內容": "、".join(r.parts or []),
                    "應保養而未保養": "、".join(missing) if missing else None,
                    "備註": r.note,
                })
                prev_hours = curr

        df = pd.DataFrame.from_records(rows)
        if not df.empty:
            df = df.dropna(how="all").sort_values(["日期", "車號"], kind="mergesort")
        return _send_df_as_excel(df, filename=f"保養紀錄_{year}.xlsx", sheet_name="保養紀錄")
