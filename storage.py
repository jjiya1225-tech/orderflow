"""
데이터 저장/불러오기 모듈
Google Sheets 기반으로 발주 데이터를 영구 저장합니다.
"""

import json
import threading
import streamlit as st
from datetime import datetime
from copy import deepcopy

import gspread
from google.oauth2.service_account import Credentials

_lock = threading.Lock()
_client = None
_sheet = None

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _get_sheet():
    """Google Sheets 연결 (캐싱)"""
    global _client, _sheet
    if _sheet is not None:
        return _sheet

    # Streamlit Secrets에서 서비스 계정 키 읽기
    creds_dict = json.loads(st.secrets["GCP_SERVICE_ACCOUNT"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    _client = gspread.authorize(creds)

    sheet_url = st.secrets.get("GOOGLE_SHEET_URL", "")
    if sheet_url:
        spreadsheet = _client.open_by_url(sheet_url)
    else:
        sheet_name = st.secrets.get("GOOGLE_SHEET_NAME", "OrderFlow-DB")
        try:
            spreadsheet = _client.open(sheet_name)
        except gspread.SpreadsheetNotFound:
            spreadsheet = _client.create(sheet_name)
            spreadsheet.share(None, perm_type="anyone", role="writer")

    # 'orders' 시트 가져오기 (없으면 생성)
    try:
        _sheet = spreadsheet.worksheet("orders")
    except gspread.WorksheetNotFound:
        _sheet = spreadsheet.add_worksheet(title="orders", rows=1000, cols=2)
        _sheet.update_cell(1, 1, "id")
        _sheet.update_cell(1, 2, "data")

    return _sheet


def _read_all_rows() -> list[dict]:
    """시트에서 모든 발주 데이터를 읽어옵니다."""
    sheet = _get_sheet()
    rows = sheet.get_all_values()
    orders = []
    for row in rows[1:]:  # 헤더 건너뛰기
        if len(row) >= 2 and row[0] and row[1]:
            try:
                order = json.loads(row[1])
                orders.append(order)
            except (json.JSONDecodeError, Exception):
                continue
    return orders


def _find_row(order_id: str) -> int | None:
    """order_id로 시트의 행 번호 찾기 (1-indexed)"""
    sheet = _get_sheet()
    ids = sheet.col_values(1)
    for i, val in enumerate(ids):
        if val == order_id:
            return i + 1  # 1-indexed
    return None


def gen_order_id() -> str:
    with _lock:
        orders = _read_all_rows()
        today = datetime.now().strftime("%Y-%m%d")
        prefix = f"PO-{today}"
        existing = [o for o in orders if o.get("id", "").startswith(prefix)]
        seq = len(existing) + 1
        return f"{prefix}-{seq:03d}"


def save_order(order: dict) -> str:
    order_id = gen_order_id()
    order["id"] = order_id
    order["created_at"] = datetime.now().isoformat()
    with _lock:
        sheet = _get_sheet()
        sheet.append_row(
            [order_id, json.dumps(order, ensure_ascii=False)],
            value_input_option="RAW",
        )
    return order_id


def load_all_orders() -> list[dict]:
    orders = _read_all_rows()
    orders.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return orders


def load_order(order_id: str) -> dict | None:
    for o in load_all_orders():
        if o["id"] == order_id:
            return deepcopy(o)
    return None


def update_order_status(order_id: str, new_status: str):
    with _lock:
        row_num = _find_row(order_id)
        if row_num is None:
            return
        sheet = _get_sheet()
        data = sheet.cell(row_num, 2).value
        if data:
            order = json.loads(data)
            order["status"] = new_status
            sheet.update_cell(row_num, 2, json.dumps(order, ensure_ascii=False))


def update_order(order_id: str, updated_data: dict):
    """발주 데이터를 업데이트합니다."""
    with _lock:
        row_num = _find_row(order_id)
        if row_num is None:
            return
        sheet = _get_sheet()
        data = sheet.cell(row_num, 2).value
        if data:
            original = json.loads(data)
            updated_data["id"] = order_id
            updated_data["created_at"] = original.get("created_at", "")
            sheet.update_cell(row_num, 2, json.dumps(updated_data, ensure_ascii=False))


def delete_order(order_id: str):
    with _lock:
        row_num = _find_row(order_id)
        if row_num is None:
            return
        sheet = _get_sheet()
        sheet.delete_rows(row_num)


def get_stats() -> dict:
    orders = load_all_orders()
    if not orders:
        return {"total": 0, "pending": 0, "shipping": 0, "suppliers": 0, "total_amount": 0}
    return {
        "total": len(orders),
        "pending": sum(1 for o in orders if o.get("status") == "확인 대기"),
        "shipping": sum(1 for o in orders if o.get("status") == "배송 중"),
        "suppliers": len(set(o.get("supplier", "") for o in orders)),
        "total_amount": sum(o.get("total_amount", 0) for o in orders),
    }


def import_orders(data: list[dict]) -> int:
    """외부 데이터를 병합합니다."""
    with _lock:
        existing = {o["id"] for o in _read_all_rows()}
        sheet = _get_sheet()
        added = 0
        for o in data:
            if o.get("id") and o["id"] not in existing:
                sheet.append_row(
                    [o["id"], json.dumps(o, ensure_ascii=False)],
                    value_input_option="RAW",
                )
                existing.add(o["id"])
                added += 1
    return added


def export_all_json() -> str:
    orders = load_all_orders()
    return json.dumps({"orders": orders}, ensure_ascii=False, indent=2)
