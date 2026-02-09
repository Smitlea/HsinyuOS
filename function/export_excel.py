# export_routes.py
from __future__ import annotations
import io
import datetime as dt
from collections import deque, defaultdict, OrderedDict

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


def norm_key(date, crane_id, site_id=None):
    """把 key 元素都標準化為 (date, str(crane_id), str(site_id) or None)"""
    return (
        date,
        str(crane_id) if crane_id is not None else None,
        str(site_id) if site_id is not None else None,
    )

def norm_key_date_crane(date, crane_id):
    return (date, str(crane_id) if crane_id is not None else None)
# ---------- 1) 日常登記 ----------
# 假設 db, DailyTask, WorkRecord, MaintenanceRecord, User, _parse_year, _send_df_as_excel 都已在你的模組中定義/匯入

def to_date(x):
    # 避免 date/datetime 混用導致 key 對不到
    return x.date() if hasattr(x, "date") else x

def norm_dc(dt, crane_id):
    return (to_date(dt), crane_id)

@api.route("/api/export/daily")
class ExportDaily(Resource):
    def get(self):
        year, start, end = _parse_year()

        # 取 DailyTask
        daily_rows = (
            db.session.query(DailyTask)
            .options(
                joinedload(DailyTask.crane),
                joinedload(DailyTask.site),
                joinedload(DailyTask.updater),
            )
            .filter(
                DailyTask.is_deleted.is_(False),
                and_(DailyTask.task_date >= start, DailyTask.task_date <= end),
            )
            .all()
        )

        # 取 WorkRecord
        wr_rows = (
            db.session.query(WorkRecord)
            .options(
                joinedload(WorkRecord.crane),
                joinedload(WorkRecord.site),
                joinedload(WorkRecord.updater),
            )
            .filter(
                WorkRecord.is_deleted.is_(False),
                and_(WorkRecord.record_date >= start, WorkRecord.record_date <= end),
            )
            .all()
        )

        tm_by_date = defaultdict(list)
        tm_rows = (
            db.session.query(TaskMaintenance)
            .options(joinedload(TaskMaintenance.creator))
            .filter(
                TaskMaintenance.is_deleted.is_(False),
                and_(TaskMaintenance.record_date >= start, TaskMaintenance.record_date <= end),
            )
            .all()
        )
        for tm in tm_rows:
            tm_by_date[to_date(tm.record_date)].append(tm)

        def fmt_task_maintenance(task_date: dt.date) -> str | None:
            """
            把同一天的 TaskMaintenance.description 彙整成一格字串（多筆用換行）
            顯示格式：暱稱: 描述
            """
            lst = tm_by_date.get(task_date, [])
            if not lst:
                return None

            lines = []
            for tm in lst:
                who = tm.nickname or ""
                if who:
                    lines.append(f"{who}: {tm.description}")
                else:
                    lines.append(f"{tm.description}")
            return "\n".join(lines)

        # MaintenanceRecord index by (record_date, crane_id)
        maint_by_key = defaultdict(list)
        mr_rows = (
            db.session.query(MaintenanceRecord)
            .filter(and_(MaintenanceRecord.record_date >= start, MaintenanceRecord.record_date <= end))
            .all()
        )
        for mr in mr_rows:
            maint_by_key[(to_date(mr.record_date), mr.crane_id)].append(mr)

        # assistants id 蒐集 + user_map
        all_assistant_ids = set()
        for wr in wr_rows:
            for a in (wr.assistants or []):
                if isinstance(a, int):
                    all_assistant_ids.add(a)

        user_map = {}
        if all_assistant_ids:
            users = db.session.query(User).filter(User.id.in_(list(all_assistant_ids))).all()
            user_map = {u.id: (u.nickname or u.username) for u in users}

        def resolve_assistants_name(assistants_list):
            seen = OrderedDict()
            for a in assistants_list:
                if isinstance(a, int):
                    name = user_map.get(a)
                    seen[name or str(a)] = None
                else:
                    seen[str(a)] = None
            return list(seen.keys())

        # --- 核心：用 (date, crane) 分群，保證 WorkRecord 都會被輸出 ---
        daily_by_dc = defaultdict(list)
        for d in daily_rows:
            daily_by_dc[norm_dc(d.task_date, d.crane_id)].append(d)

        wr_by_dc = defaultdict(list)
        for wr in wr_rows:
            wr_by_dc[norm_dc(wr.record_date, wr.crane_id)].append(wr)

        # union keys：只要在 range 內出現過 DailyTask 或 WorkRecord 都會處理到
        all_keys = sorted(set(daily_by_dc.keys()) | set(wr_by_dc.keys()), key=lambda k: (k[0], k[1] or 0))

        records = []

        for (dt_key, crane_id) in all_keys:
            d_list = daily_by_dc.get((dt_key, crane_id), [])
            w_list = wr_by_dc.get((dt_key, crane_id), [])

            task_maint_text = fmt_task_maintenance(dt_key)


            wrs_by_site = defaultdict(deque)
            wrs_no_site = deque()

            for wr in w_list:
                if wr.site_id:
                    wrs_by_site[wr.site_id].append(wr)
                else:
                    wrs_no_site.append(wr)

            for d in d_list:
                records.append({
                    "日期": to_date(d.task_date),
                    "廠商": d.vendor,
                    "車號": d.crane.crane_number if d.crane else None,
                    "地點": d.site.location if d.site else None,
                    "人員": d.updated_by_nickname,
                    "時數": d.work_time,
                    "吊怪手200": None,
                    "吊怪手120": None,
                    "輔助人員A": None,
                    "輔助人員B": None,
                    "輔助人員C": None,
                    "輔助人員D": None,
                    "當日保養": task_maint_text,
                    "備註": d.note or None,
                })

                # 精準配對：同 site 的 WorkRecord 全部輸出
                q = wrs_by_site.get(d.site_id)
                while q and len(q) > 0:
                    wr = q.popleft()
                    assistants_raw = wr.assistants or []
                    assistant_names = resolve_assistants_name(assistants_raw) if assistants_raw else []
                    assistant_names = (assistant_names + [None, None, None, None])[:4]

                    records.append({
                        "日期": to_date(wr.record_date),
                        "廠商": wr.vendor or d.vendor,
                        "車號": wr.crane.crane_number if wr.crane else (d.crane.crane_number if d.crane else None),
                        "地點": wr.site.location if wr.site else (d.site.location if d.site else None),
                        "人員": getattr(wr, "updated_by_nickname", None),
                        "時數": None,
                        "吊怪手200": wr.qty_200 if getattr(wr, "qty_200", None) is not None else None,
                        "吊怪手120": wr.qty_120 if getattr(wr, "qty_120", None) is not None else None,
                        "輔助人員A": assistant_names[0],
                        "輔助人員B": assistant_names[1],
                        "輔助人員C": assistant_names[2],
                        "輔助人員D": assistant_names[3],
                        "當日保養": task_maint_text,
                        "備註": wr.note or None,
                    })

            # 2) 群組內剩餘的 WorkRecord（沒對到 site / 沒 site / 沒 DailyTask）照樣輸出
            fallback_vendor = d_list[0].vendor if d_list else None
            fallback_site_location = (d_list[0].site.location if (d_list and d_list[0].site) else None)
            fallback_crane_number = (d_list[0].crane.crane_number if (d_list and d_list[0].crane) else None)

            # 先輸出 wrs_no_site
            while wrs_no_site:
                wr = wrs_no_site.popleft()
                assistants_raw = wr.assistants or []
                assistant_names = resolve_assistants_name(assistants_raw) if assistants_raw else []
                assistant_names = (assistant_names + [None, None, None, None])[:4]

                records.append({
                    "日期": to_date(wr.record_date),
                    "廠商": wr.vendor or fallback_vendor,
                    "車號": wr.crane.crane_number if wr.crane else fallback_crane_number,
                    "地點": wr.site.location if wr.site else fallback_site_location,
                    "人員": getattr(wr, "updated_by_nickname", None),
                    "時數": None,
                    "吊怪手200": wr.qty_200 if getattr(wr, "qty_200", None) is not None else None,
                    "吊怪手120": wr.qty_120 if getattr(wr, "qty_120", None) is not None else None,
                    "輔助人員A": assistant_names[0],
                    "輔助人員B": assistant_names[1],
                    "輔助人員C": assistant_names[2],
                    "輔助人員D": assistant_names[3],
                    "當日保養": task_maint_text,
                    "備註": wr.note or None,
                })

            # 再輸出 wrs_by_site 裡剩下的
            for site_id, q in list(wrs_by_site.items()):
                while q:
                    wr = q.popleft()
                    assistants_raw = wr.assistants or []
                    assistant_names = resolve_assistants_name(assistants_raw) if assistants_raw else []
                    assistant_names = (assistant_names + [None, None, None, None])[:4]

                    records.append({
                        "日期": to_date(wr.record_date),
                        "廠商": wr.vendor or fallback_vendor,
                        "車號": wr.crane.crane_number if wr.crane else fallback_crane_number,
                        "地點": wr.site.location if wr.site else fallback_site_location,
                        "人員": getattr(wr, "updated_by_nickname", None),
                        "時數": None,
                        "吊怪手200": wr.qty_200 if getattr(wr, "qty_200", None) is not None else None,
                        "吊怪手120": wr.qty_120 if getattr(wr, "qty_120", None) is not None else None,
                        "輔助人員A": assistant_names[0],
                        "輔助人員B": assistant_names[1],
                        "輔助人員C": assistant_names[2],
                        "輔助人員D": assistant_names[3],
                        "當日保養": task_maint_text,
                        "備註": wr.note or None,
                    })

        # 轉 DataFrame 並回傳 Excel
        df = pd.DataFrame.from_records(records)
        if not df.empty:
            df = df.dropna(how="all")
            df = df.sort_values(["日期", "車號"], kind="mergesort")

        return _send_df_as_excel(df, filename=f"日常登記_{year}.xlsx", sheet_name="日常登記")
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
