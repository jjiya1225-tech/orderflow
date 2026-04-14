"""
데이터 저장/불러오기 모듈
로컬 JSON 파일 기반으로 발주 데이터를 저장합니다.
"""

import json
import os
import threading
from datetime import datetime
from copy import deepcopy

_lock = threading.Lock()

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DATA_FILE = os.path.join(DATA_DIR, "orders.json")


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _read_all() -> list[dict]:
    _ensure_dir()
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("orders", [])
    except (json.JSONDecodeError, Exception):
        return []


def _write_all(orders: list[dict]):
    _ensure_dir()
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"orders": orders}, f, ensure_ascii=False, indent=2)


def gen_order_id() -> str:
    with _lock:
        orders = _read_all()
        today = datetime.now().strftime("%Y-%m%d")
        prefix = f"PO-{today}"
        existing = [o for o in orders if o.get("id", "").startswith(prefix)]
        seq = len(existing) + 1
        return f"{prefix}-{seq:03d}"


def save_order(order: dict) -> str:
    with _lock:
        orders = _read_all()
        order_id = gen_order_id()
        order["id"] = order_id
        order["created_at"] = datetime.now().isoformat()
        orders.append(order)
        _write_all(orders)
    return order_id


def load_all_orders() -> list[dict]:
    orders = _read_all()
    orders.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return orders


def load_order(order_id: str) -> dict | None:
    for o in _read_all():
        if o.get("id") == order_id:
            return deepcopy(o)
    return None


def update_order_status(order_id: str, new_status: str):
    with _lock:
        orders = _read_all()
        for o in orders:
            if o.get("id") == order_id:
                o["status"] = new_status
                break
        _write_all(orders)


def update_order(order_id: str, updated_data: dict):
    """발주 데이터를 업데이트합니다."""
    with _lock:
        orders = _read_all()
        for i, o in enumerate(orders):
            if o.get("id") == order_id:
                updated_data["id"] = order_id
                updated_data["created_at"] = o.get("created_at", "")
                orders[i] = updated_data
                break
        _write_all(orders)


def delete_order(order_id: str):
    with _lock:
        orders = _read_all()
        orders = [o for o in orders if o.get("id") != order_id]
        _write_all(orders)


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
        orders = _read_all()
        existing = {o["id"] for o in orders}
        added = 0
        for o in data:
            if o.get("id") and o["id"] not in existing:
                orders.append(o)
                existing.add(o["id"])
                added += 1
        if added > 0:
            _write_all(orders)
    return added


def export_all_json() -> str:
    orders = load_all_orders()
    return json.dumps({"orders": orders}, ensure_ascii=False, indent=2)
