"""
데이터 저장/불러오기 모듈
GitHub 레포의 data.json 파일을 DB로 사용합니다.
재부팅해도 데이터가 유지됩니다.
"""

import json
import threading
import streamlit as st
from datetime import datetime
from copy import deepcopy
import base64
import requests

_lock = threading.Lock()
_cache = None
_cache_sha = None

DATA_PATH = "data.json"


def _gh_headers():
    token = st.secrets["GITHUB_TOKEN"]
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }


def _gh_url():
    repo = st.secrets["GITHUB_REPO"]
    return f"https://api.github.com/repos/{repo}/contents/{DATA_PATH}"


def _read_remote() -> tuple[list[dict], str | None]:
    """GitHub에서 data.json 읽기. (orders, sha) 반환"""
    global _cache, _cache_sha
    try:
        r = requests.get(_gh_url(), headers=_gh_headers(), timeout=15)
        if r.status_code == 200:
            info = r.json()
            sha = info["sha"]
            content = base64.b64decode(info["content"]).decode("utf-8")
            data = json.loads(content)
            orders = data.get("orders", [])
            _cache = orders
            _cache_sha = sha
            return orders, sha
        elif r.status_code == 404:
            _cache = []
            _cache_sha = None
            return [], None
        else:
            return _cache or [], _cache_sha
    except Exception:
        return _cache or [], _cache_sha


def _write_remote(orders: list[dict]):
    """GitHub에 data.json 저장"""
    global _cache, _cache_sha
    content_str = json.dumps({"orders": orders}, ensure_ascii=False, indent=2)
    encoded = base64.b64encode(content_str.encode("utf-8")).decode("utf-8")

    body = {
        "message": f"Update orders ({datetime.now().strftime('%Y-%m-%d %H:%M')})",
        "content": encoded,
    }
    if _cache_sha:
        body["sha"] = _cache_sha

    r = requests.put(_gh_url(), headers=_gh_headers(), json=body, timeout=15)
    if r.status_code in (200, 201):
        _cache = orders
        _cache_sha = r.json().get("content", {}).get("sha", _cache_sha)
    else:
        raise Exception(f"GitHub 저장 실패: {r.status_code} {r.text[:200]}")


def gen_order_id() -> str:
    orders, _ = _read_remote()
    today = datetime.now().strftime("%Y-%m%d")
    prefix = f"PO-{today}"
    existing = [o for o in orders if o.get("id", "").startswith(prefix)]
    seq = len(existing) + 1
    return f"{prefix}-{seq:03d}"


def save_order(order: dict) -> str:
    with _lock:
        order_id = gen_order_id()
        order["id"] = order_id
        order["created_at"] = datetime.now().isoformat()
        orders, _ = _read_remote()
        orders.append(order)
        _write_remote(orders)
    return order_id


def load_all_orders() -> list[dict]:
    orders, _ = _read_remote()
    orders.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return orders


def load_order(order_id: str) -> dict | None:
    orders, _ = _read_remote()
    for o in orders:
        if o.get("id") == order_id:
            return deepcopy(o)
    return None


def update_order_status(order_id: str, new_status: str):
    with _lock:
        orders, _ = _read_remote()
        for o in orders:
            if o.get("id") == order_id:
                o["status"] = new_status
                break
        _write_remote(orders)


def update_order(order_id: str, updated_data: dict):
    """발주 데이터를 업데이트합니다."""
    with _lock:
        orders, _ = _read_remote()
        for i, o in enumerate(orders):
            if o.get("id") == order_id:
                updated_data["id"] = order_id
                updated_data["created_at"] = o.get("created_at", "")
                orders[i] = updated_data
                break
        _write_remote(orders)


def delete_order(order_id: str):
    with _lock:
        orders, _ = _read_remote()
        orders = [o for o in orders if o.get("id") != order_id]
        _write_remote(orders)


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
        orders, _ = _read_remote()
        existing_ids = {o["id"] for o in orders}
        added = 0
        for o in data:
            if o.get("id") and o["id"] not in existing_ids:
                orders.append(o)
                existing_ids.add(o["id"])
                added += 1
        if added > 0:
            _write_remote(orders)
    return added


def export_all_json() -> str:
    orders = load_all_orders()
    return json.dumps({"orders": orders}, ensure_ascii=False, indent=2)
