"""
데이터 저장/불러오기 모듈
JSON 파일 기반으로 발주 데이터를 관리합니다.
"""

import json
import threading
from pathlib import Path
from datetime import datetime
from copy import deepcopy

DATA_DIR = Path("data")
DATA_FILE = DATA_DIR / "orders.json"
_lock = threading.Lock()


def _ensure():
    DATA_DIR.mkdir(exist_ok=True)
    if not DATA_FILE.exists():
        DATA_FILE.write_text(json.dumps({"orders": [], "next_seq": {}}, ensure_ascii=False))


def _read_db() -> dict:
    _ensure()
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def _write_db(db: dict):
    _ensure()
    DATA_FILE.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")


def gen_order_id() -> str:
    with _lock:
        db = _read_db()
        today = datetime.now().strftime("%Y-%m%d")
        prefix = f"PO-{today}"
        seq_key = prefix
        if seq_key not in db["next_seq"]:
            existing = [o for o in db["orders"] if o["id"].startswith(prefix)]
            db["next_seq"][seq_key] = len(existing) + 1
        seq = db["next_seq"][seq_key]
        db["next_seq"][seq_key] = seq + 1
        _write_db(db)
        return f"{prefix}-{seq:03d}"


def save_order(order: dict) -> str:
    order_id = gen_order_id()
    order["id"] = order_id
    order["created_at"] = datetime.now().isoformat()
    with _lock:
        db = _read_db()
        db["orders"].insert(0, order)
        _write_db(db)
    return order_id


def load_all_orders() -> list[dict]:
    return _read_db().get("orders", [])


def load_order(order_id: str) -> dict | None:
    for o in load_all_orders():
        if o["id"] == order_id:
            return deepcopy(o)
    return None


def update_order_status(order_id: str, new_status: str):
    with _lock:
        db = _read_db()
        for o in db["orders"]:
            if o["id"] == order_id:
                o["status"] = new_status
                break
        _write_db(db)


def delete_order(order_id: str):
    with _lock:
        db = _read_db()
        db["orders"] = [o for o in db["orders"] if o["id"] != order_id]
        _write_db(db)


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
    """외부 데이터를 병합합니다. 중복 ID는 건너뜁니다."""
    with _lock:
        db = _read_db()
        existing_ids = {o["id"] for o in db["orders"]}
        added = 0
        for o in data:
            if o.get("id") and o["id"] not in existing_ids:
                db["orders"].append(o)
                existing_ids.add(o["id"])
                added += 1
        db["orders"].sort(key=lambda x: x.get("created_at", ""), reverse=True)
        _write_db(db)
    return added


def export_all_json() -> str:
    return json.dumps(_read_db(), ensure_ascii=False, indent=2)
