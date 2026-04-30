"""
OrderFlow - AI 발주 관리 시스템 v4
발주서/인보이스 구분 · 연결 건 그룹화 · 휠 캘린더
"""

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import json as _json
from datetime import datetime, timedelta
from io import BytesIO
from calendar import monthrange

from parser import parse_file
from storage import (
    save_order, load_all_orders, load_order, update_order_status,
    delete_order, get_stats, export_all_json, import_orders, update_order,
)

st.set_page_config(page_title="OrderFlow", page_icon="📦", layout="wide", initial_sidebar_state="expanded")
API_KEY = st.secrets.get("ANTHROPIC_API_KEY", "")

# ════════════════════════════════════════════
# CSS
# ════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Noto+Sans+KR:wght@300;400;500;600;700&display=swap');
html, body, [class*="css"] {
    font-family: 'Inter', 'Noto Sans KR', -apple-system, BlinkMacSystemFont, sans-serif;
    -webkit-font-smoothing: antialiased;
}
.stApp { background: #fafafa; }
.block-container { padding-top: 2rem; max-width: 960px; }

/* 사이드바 */
[data-testid="stSidebar"] {
    background: #ffffff;
    border-right: 1px solid #f0f0f0;
}

/* 메트릭 카드 */
[data-testid="stMetric"] {
    background: #ffffff;
    border: 1px solid #f0f0f0;
    border-radius: 16px;
    padding: 20px 22px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.03);
}
[data-testid="stMetricLabel"] { font-size: 12px; font-weight: 500; color: #86868b; }
[data-testid="stMetricValue"] { font-size: 28px; font-weight: 700; color: #1d1d1f; }

/* 버튼 */
.stButton > button {
    border-radius: 12px;
    font-weight: 500;
    font-size: 14px;
    padding: 8px 20px;
    border: 1px solid #d2d2d7;
}
.stButton > button[kind="primary"] {
    background: #0071e3;
    border-color: #0071e3;
    color: white;
}

/* 입력 필드 */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea {
    border-radius: 10px;
    border-color: #d2d2d7;
}

/* Expander */
div[data-testid="stExpander"] {
    border: 1px solid #f0f0f0;
    border-radius: 14px;
    background: white;
}

/* 유형 뱃지 */
.badge-po {
    display: inline-block;
    background: #dbeafe;
    color: #1d4ed8;
    font-size: 11px;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 6px;
    margin-right: 4px;
}
.badge-inv {
    display: inline-block;
    background: #fef3c7;
    color: #92400e;
    font-size: 11px;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 6px;
    margin-right: 4px;
}
.group-divider {
    border-top: 1px dashed #e5e7eb;
    margin: 12px 0;
    position: relative;
}
.group-divider::after {
    content: '🔗 연결';
    position: absolute;
    top: -10px;
    left: 50%;
    transform: translateX(-50%);
    background: white;
    padding: 0 8px;
    font-size: 11px;
    color: #9ca3af;
}
</style>
""", unsafe_allow_html=True)


def fmt_amount(amt, cur="KRW"):
    if not amt:
        return "-"
    sym = {"KRW": "₩", "CNY": "¥", "USD": "$", "JPY": "¥"}.get(cur, "")
    return f"{sym}{amt:,.0f}"


def date_label(doc_type, field):
    """doc_type에 따라 날짜 라벨 반환"""
    if doc_type == "인보이스":
        return {"order_date": "출고일", "eta": "도착예정일"}.get(field, field)
    return {"order_date": "발주일", "eta": "입고예정일"}.get(field, field)


def group_orders(orders):
    """연결된 발주서-인보이스를 묶어서 그룹화"""
    shown = set()
    groups = []
    order_map = {o["id"]: o for o in orders}
    for o in orders:
        if o["id"] in shown:
            continue
        shown.add(o["id"])
        group = [o]
        linked_id = o.get("linked_id")
        if linked_id and linked_id in order_map and linked_id not in shown:
            group.append(order_map[linked_id])
            shown.add(linked_id)
        # 발주서를 앞에, 인보이스를 뒤에
        group.sort(key=lambda x: 0 if x.get("doc_type") == "발주서" else 1)
        groups.append(group)
    return groups


# ════════════════════════════════════════════
# 가격 자동 계산
# ════════════════════════════════════════════
DEFAULT_RATES = {"CNY": 220, "USD": 1500, "JPY": 10, "KRW": 1}
DEFAULT_VENDOR_MULTI = 2
DEFAULT_ONLINE_MULTI = 3
DEFAULT_ROUND_UNIT = 100

if "exchange_rates" not in st.session_state:
    st.session_state["exchange_rates"] = dict(DEFAULT_RATES)
if "vendor_multi" not in st.session_state:
    st.session_state["vendor_multi"] = DEFAULT_VENDOR_MULTI
if "online_multi" not in st.session_state:
    st.session_state["online_multi"] = DEFAULT_ONLINE_MULTI
if "round_unit" not in st.session_state:
    st.session_state["round_unit"] = DEFAULT_ROUND_UNIT


def get_rates():
    return st.session_state["exchange_rates"]

def get_vendor_multi():
    return st.session_state["vendor_multi"]

def get_online_multi():
    return st.session_state["online_multi"]

def get_round_unit():
    return st.session_state["round_unit"]


def round_price(v, unit=None):
    if unit is None:
        unit = get_round_unit()
    return int((v / unit) + 0.5) * unit


def calc_prices(unit_price, currency):
    try:
        unit_price = float(unit_price or 0)
    except (TypeError, ValueError):
        unit_price = 0
    rate = get_rates().get(currency, 1)
    krw = round_price(unit_price * rate)
    vendor = round_price(krw * get_vendor_multi())
    online = round_price(krw * get_online_multi())
    return krw, vendor, online


def add_calc_prices(items, currency):
    for it in items:
        raw_price = it.get("unit_price", 0)
        try:
            price = float(raw_price or 0)
        except (TypeError, ValueError):
            price = 0
        krw, vendor, online = calc_prices(price, currency)
        it["krw_price"] = krw
        it["vendor_price"] = vendor
        it["online_price"] = online
    return items


def parse_date(s):
    if not s:
        return None
    if isinstance(s, datetime):
        return s.date()
    from datetime import date as _date
    if isinstance(s, _date):
        return s
    s = str(s).strip().replace("/", "-").replace(".", "-")
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def render_order_items_table(items, currency, show_images=True):
    """품목 테이블 렌더링 (공통)"""
    has_img = show_images and any(it.get("image") for it in items)
    rows = []
    for it in items:
        display = it.get("display_name") or ""
        name = it.get("name", "")
        show_name = display if display else name
        color = it.get("color") or ""
        if color:
            show_name = f"{show_name} ({color})"
        if it.get("krw_price"):
            krw = it["krw_price"]
            vendor = it["vendor_price"]
            online = it["online_price"]
        else:
            krw, vendor, online = calc_prices(it.get("unit_price", 0), currency)
        qty = it.get("quantity", 0)
        row = {}
        if has_img:
            row["이미지"] = it.get("image") or ""
        row["제품명"] = show_name
        row["수량"] = qty
        row["단가"] = f"₩{krw:,.0f}"
        row["업체가"] = f"₩{vendor:,.0f}"
        row["온라인가"] = f"₩{online:,.0f}"
        row["총금액"] = f"₩{qty * krw:,.0f}"
        rows.append(row)
    df = pd.DataFrame(rows)
    col_config = {}
    if has_img:
        col_config["이미지"] = st.column_config.ImageColumn("이미지", width="small")
    st.dataframe(df, use_container_width=True, hide_index=True, column_config=col_config)


def render_order_card(o, compact=False):
    """단일 주문 카드 렌더링 (대시보드용)"""
    doc_type = o.get("doc_type", "발주서")
    badge_cls = "badge-po" if doc_type == "발주서" else "badge-inv"
    items = o.get("items", [])
    total_qty = sum(i.get("quantity", 0) for i in items)
    o_cur = o.get("currency", "KRW")

    st.markdown(f'<span class="{badge_cls}">{doc_type}</span> **{o["id"]}**', unsafe_allow_html=True)

    # 날짜 라벨 (doc_type에 따라)
    od_label = date_label(doc_type, "order_date")
    eta_label = date_label(doc_type, "eta")
    if doc_type == "발주서":
        st.caption(f"{od_label}: {o.get('order_date', '-')}  |  {total_qty:,}개 · {len(items)}종")
    else:
        st.caption(
            f"{od_label}: {o.get('order_date', '-')}  |  "
            f"{eta_label}: {o.get('eta') or '-'}  |  "
            f"{total_qty:,}개 · {len(items)}종"
        )

    if not compact:
        render_order_items_table(items, o_cur)
        if o.get("notes"):
            st.info(f"📝 {o['notes']}")


# ════════════════════════════════════════════
# 캘린더 JS 컴포넌트 (휠 스크롤)
# ════════════════════════════════════════════
def render_wheel_calendar(orders):
    """애플 캘린더 스타일 휠 스크롤 캘린더"""
    now = datetime.now()

    # 모든 ETA 데이터 수집 (날짜별 건수 + 지연 여부)
    eta_data = {}
    for o in orders:
        if o.get("eta") and o.get("status") != "입고 완료":
            eta_str = o["eta"]
            if eta_str not in eta_data:
                eta_data[eta_str] = 0
            eta_data[eta_str] += 1

    eta_json = _json.dumps(eta_data, ensure_ascii=False)
    today_str = now.strftime("%Y-%m-%d")

    cal_html = f"""
    <div id="cal-wrap" style="
        font-family: -apple-system, 'Inter', 'Noto Sans KR', sans-serif;
        user-select: none;
        padding: 16px 0;
    ">
        <div id="cal-header" style="
            text-align: center;
            margin-bottom: 16px;
            position: relative;
        ">
            <div id="cal-title" style="
                font-size: 22px;
                font-weight: 700;
                color: #1d1d1f;
                transition: opacity 0.2s;
            "></div>
            <div style="
                font-size: 11px;
                color: #adb5bd;
                margin-top: 4px;
            ">스크롤하여 월 이동</div>
        </div>
        <div id="cal-weekdays" style="
            display: grid;
            grid-template-columns: repeat(7, 1fr);
            margin-bottom: 4px;
        "></div>
        <div id="cal-grid" style="
            display: grid;
            grid-template-columns: repeat(7, 1fr);
            gap: 2px;
            transition: opacity 0.15s ease, transform 0.15s ease;
        "></div>
    </div>

    <script>
    (function() {{
        const orderData = {eta_json};
        const todayStr = "{today_str}";
        const todayParts = todayStr.split('-').map(Number);
        let year = {now.year};
        let month = {now.month};

        const weekdays = ['일', '월', '화', '수', '목', '금', '토'];
        const wdContainer = document.getElementById('cal-weekdays');
        weekdays.forEach((w, i) => {{
            const el = document.createElement('div');
            el.textContent = w;
            el.style.cssText = 'text-align:center;font-size:12px;font-weight:600;padding:6px 0;color:' + (i === 0 ? '#ef4444' : i === 6 ? '#3b82f6' : '#86868b');
            wdContainer.appendChild(el);
        }});

        function daysInMonth(y, m) {{ return new Date(y, m, 0).getDate(); }}
        function firstDay(y, m) {{ return new Date(y, m - 1, 1).getDay(); }}

        function pad(n) {{ return n < 10 ? '0' + n : '' + n; }}

        function render() {{
            const title = document.getElementById('cal-title');
            title.textContent = year + '년 ' + month + '월';

            const grid = document.getElementById('cal-grid');
            grid.innerHTML = '';
            const fd = firstDay(year, month);
            const nd = daysInMonth(year, month);

            for (let i = 0; i < fd; i++) {{
                const c = document.createElement('div');
                c.style.cssText = 'text-align:center;padding:10px 4px;min-height:44px;';
                grid.appendChild(c);
            }}

            for (let d = 1; d <= nd; d++) {{
                const c = document.createElement('div');
                const dateStr = year + '-' + pad(month) + '-' + pad(d);
                const count = orderData[dateStr] || 0;
                const isToday = (year === todayParts[0] && month === todayParts[1] && d === todayParts[2]);
                const dayOfWeek = (fd + d - 1) % 7;

                let bg = 'transparent';
                let fontWeight = '400';
                let textColor = dayOfWeek === 0 ? '#ef4444' : dayOfWeek === 6 ? '#3b82f6' : '#1d1d1f';

                if (isToday) {{
                    bg = '#1d1d1f';
                    textColor = '#ffffff';
                    fontWeight = '700';
                }}

                let isPast = false;
                if (count > 0) {{
                    const dd = new Date(year, month - 1, d);
                    const td = new Date(todayParts[0], todayParts[1] - 1, todayParts[2]);
                    isPast = dd < td;
                }}

                c.style.cssText = 'text-align:center;padding:6px 4px;min-height:44px;border-radius:12px;font-size:14px;background:' + bg + ';font-weight:' + fontWeight + ';color:' + textColor + ';position:relative;';

                let html = '<span style="' + (isToday ? 'display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:50%;' : '') + '">' + d + '</span>';

                if (count > 0) {{
                    const dotColor = isPast ? '#ef4444' : '#0071e3';
                    html += '<div style="width:6px;height:6px;border-radius:50%;background:' + dotColor + ';margin:3px auto 0;"></div>';
                    if (!isToday) {{
                        c.style.background = isPast ? '#fef2f2' : '#eff6ff';
                    }}
                }}

                c.innerHTML = html;
                grid.appendChild(c);
            }}
        }}

        // 휠 이벤트 (디바운스)
        let locked = false;
        const wrap = document.getElementById('cal-wrap');
        wrap.addEventListener('wheel', function(e) {{
            e.preventDefault();
            if (locked) return;
            locked = true;
            setTimeout(function() {{ locked = false; }}, 280);

            const grid = document.getElementById('cal-grid');
            const dir = e.deltaY > 0 ? 1 : -1;

            // 페이드 아웃
            grid.style.opacity = '0';
            grid.style.transform = 'translateY(' + (dir * -8) + 'px)';

            setTimeout(function() {{
                month += dir;
                if (month > 12) {{ month = 1; year++; }}
                if (month < 1) {{ month = 12; year--; }}
                render();
                grid.style.transform = 'translateY(' + (dir * 8) + 'px)';
                // 트리거 리플로우
                void grid.offsetHeight;
                grid.style.opacity = '1';
                grid.style.transform = 'translateY(0)';
            }}, 120);
        }}, {{ passive: false }});

        // 터치 스와이프
        let touchStartY = 0;
        wrap.addEventListener('touchstart', function(e) {{
            touchStartY = e.touches[0].clientY;
        }}, {{ passive: true }});
        wrap.addEventListener('touchend', function(e) {{
            const diff = touchStartY - e.changedTouches[0].clientY;
            if (Math.abs(diff) > 40) {{
                const dir = diff > 0 ? 1 : -1;
                month += dir;
                if (month > 12) {{ month = 1; year++; }}
                if (month < 1) {{ month = 12; year--; }}
                render();
            }}
        }}, {{ passive: true }});

        render();
    }})();
    </script>
    """
    components.html(cal_html, height=400, scrolling=False)


# ════════════════════════════════════════════
# 사이드바
# ════════════════════════════════════════════
with st.sidebar:
    st.markdown("#### 📦 OrderFlow")
    st.caption("AI 발주 관리")
    st.markdown("---")
    page = st.radio(
        "메뉴",
        ["📊 대시보드", "⬆️ 발주서 업로드", "📋 발주 목록", "🔧 관리"],
        label_visibility="collapsed",
    )
    st.markdown("---")
    if API_KEY:
        st.caption("● AI 연결됨")
    else:
        st.caption("● API 미설정")


# ════════════════════════════════════════════
# 📊 대시보드
# ════════════════════════════════════════════
if page == "📊 대시보드":
    st.title("대시보드")
    st.caption("발주 현황을 한눈에 확인하세요")

    orders = load_all_orders()
    stats = get_stats()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("전체 발주", f"{stats['total']}건")
    c2.metric("확인 대기", f"{stats['pending']}건")
    c3.metric("배송 중", f"{stats['shipping']}건")
    c4.metric("거래처", f"{stats['suppliers']}곳")

    if not orders:
        st.markdown("---")
        st.info("발주서를 업로드하여 시작하세요.")

    else:
        st.markdown("---")
        today_str = datetime.now().strftime("%Y-%m-%d")
        now = datetime.now()

        # ── 입고 캘린더 (휠 스크롤) ──
        render_wheel_calendar(orders)

        # ── 입고 예정 리스트 (전체, ETA 순) ──
        upcoming = []
        for o in orders:
            if o.get("eta") and o.get("status") != "입고 완료":
                upcoming.append(o)
        upcoming.sort(key=lambda x: x.get("eta", "9999"))

        if upcoming:
            st.markdown("")
            for o in upcoming[:15]:
                eta_str = o["eta"]
                is_past = eta_str < today_str
                items = o.get("items", [])
                total_qty = sum(i.get("quantity", 0) for i in items)
                doc_type = o.get("doc_type", "발주서")
                dtype_icon = "📋" if doc_type == "발주서" else "📄"
                eta_dt = parse_date(eta_str)
                eta_display = f"{eta_dt.month}/{eta_dt.day}" if eta_dt else eta_str

                if is_past:
                    days_late = (now - datetime.strptime(eta_str, "%Y-%m-%d")).days
                    label = f"🔴  {eta_display} — {dtype_icon} {o.get('supplier', '')}  ·  **{days_late}일 지연**"
                else:
                    label = f"🔵  {eta_display} — {dtype_icon} {o.get('supplier', '')}"

                with st.expander(label, expanded=is_past):
                    rows = []
                    for it in items:
                        display = it.get("display_name") or ""
                        name = it.get("name", "")
                        show_name = display if display else name
                        color = it.get("color") or ""
                        if color:
                            show_name = f"{show_name} ({color})"
                        rows.append({"품목": show_name, "수량": it.get("quantity", 0)})
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                    st.caption(f"총 {total_qty:,}개  ·  {fmt_amount(o.get('total_amount'), o.get('currency'))}")

        st.markdown("---")

        # ── 전체 발주 목록 (그룹화) ──
        st.subheader("전체 발주")

        status_filter = st.selectbox(
            "필터",
            ["전체", "확인 대기", "확인 완료", "배송 중", "입고 완료"],
            label_visibility="collapsed",
        )
        filtered = orders if status_filter == "전체" else [o for o in orders if o.get("status") == status_filter]

        groups = group_orders(filtered)

        for group in groups[:20]:
            if len(group) == 1:
                # ── 단독 건 ──
                o = group[0]
                doc_type = o.get("doc_type", "발주서")
                d_icon = "📋" if doc_type == "발주서" else "📄"
                status = o.get("status", "확인 대기")
                items = o.get("items", [])
                total_qty = sum(i.get("quantity", 0) for i in items)

                header = f"{d_icon} **[{doc_type}]** {o['id']}  ·  {o.get('supplier', '')}  ·  {fmt_amount(o.get('total_amount'), o.get('currency'))}  ·  {status}"
                with st.expander(header):
                    render_order_card(o)

            else:
                # ── 연결된 건 (발주서 + 인보이스) ──
                po = group[0]
                inv = group[1] if len(group) > 1 else None
                supplier = po.get("supplier") or (inv.get("supplier") if inv else "")
                status_po = po.get("status", "확인 대기")

                header = f"🔗 **[발주서+인보이스]** {po['id']} + {inv['id']}  ·  {supplier}  ·  {status_po}"
                with st.expander(header):
                    render_order_card(po)
                    if inv:
                        st.markdown('<div class="group-divider"></div>', unsafe_allow_html=True)
                        render_order_card(inv)


# ════════════════════════════════════════════
# ⬆️ 파일 업로드 (발주서 / 인보이스)
# ════════════════════════════════════════════
elif page == "⬆️ 발주서 업로드":
    st.title("파일 업로드")
    st.caption("발주서 또는 인보이스를 올리면 AI가 자동 분석 후 등록합니다")

    if not API_KEY:
        st.error("Claude API 키가 설정되지 않았습니다. 관리자에게 문의하세요.")
        st.stop()

    # 유형 선택
    if "upload_doc_type" not in st.session_state:
        st.session_state["upload_doc_type"] = "발주서"
    type_col1, type_col2 = st.columns(2)
    with type_col1:
        if st.button("📋 발주서", use_container_width=True,
                     type="primary" if st.session_state["upload_doc_type"] == "발주서" else "secondary"):
            st.session_state["upload_doc_type"] = "발주서"
            st.session_state["upload_results"] = {}
            st.rerun()
    with type_col2:
        if st.button("📄 인보이스", use_container_width=True,
                     type="primary" if st.session_state["upload_doc_type"] == "인보이스" else "secondary"):
            st.session_state["upload_doc_type"] = "인보이스"
            st.session_state["upload_results"] = {}
            st.rerun()

    doc_type = st.session_state["upload_doc_type"]
    st.markdown("")

    uploaded_files = st.file_uploader(
        f"{doc_type} 파일 선택 (여러 개 가능)",
        type=["xlsx", "xls", "csv", "pdf", "jpg", "jpeg", "png", "webp"],
        help="Excel, PDF, 이미지 파일 지원",
        accept_multiple_files=True,
    )

    if uploaded_files:
        if "upload_results" not in st.session_state:
            st.session_state["upload_results"] = {}

        results = st.session_state["upload_results"]

        for uploaded in uploaded_files:
            file_key = f"{uploaded.name}_{uploaded.size}"

            if file_key in results and results[file_key].get("done"):
                continue

            if file_key not in results:
                st.info(f"⏳ **{uploaded.name}** 분석 중...")
                try:
                    uploaded.seek(0)
                    parsed = parse_file(uploaded, API_KEY)
                    results[file_key] = {"parsed": parsed, "file_name": uploaded.name, "done": False}
                    st.session_state["upload_results"] = results
                    st.rerun()
                except Exception as e:
                    results[file_key] = {"error": str(e), "file_name": uploaded.name, "done": True}
                    st.session_state["upload_results"] = results
                    st.rerun()

        # ── 결과 표시 ──
        has_pending = False
        for file_key, res in results.items():
            fname = res.get("file_name", "")

            if res.get("error"):
                st.error(f"**{fname}** — 분석 실패: {res['error']}")
                continue

            if res.get("done") and res.get("order_id"):
                dtype = res.get("doc_type", "")
                icnt = res.get("item_count", 0)
                imgcnt = res.get("img_count", 0)
                dtype_icon = "📋" if dtype == "발주서" else "📄"
                extra = f"  ·  {icnt}개 품목  ·  {imgcnt}개 이미지" if icnt else ""
                st.success(f"{dtype_icon} **{fname}** → {res.get('order_id')} {dtype} 등록 완료{extra}")
                continue

            parsed = res.get("parsed")
            if not parsed:
                continue

            has_pending = True
            items = parsed.get("items", [])
            currency = parsed.get("currency", "KRW")
            items = add_calc_prices(items, currency)

            total_qty = sum(i.get("quantity", 0) for i in items)
            total_krw = sum(i.get("quantity", 0) * i.get("krw_price", 0) for i in items)
            img_count = sum(1 for i in items if i.get("image"))

            st.markdown("---")
            # 유형 뱃지 + 파일명
            badge_cls = "badge-po" if doc_type == "발주서" else "badge-inv"
            st.markdown(f'<span class="{badge_cls}">{doc_type}</span> **{fname}**', unsafe_allow_html=True)

            # 거래처 + 날짜 (유형별 라벨)
            od_label = date_label(doc_type, "order_date")
            eta_label = date_label(doc_type, "eta")
            info1, info2 = st.columns([3, 1])
            with info1:
                if doc_type == "발주서":
                    st.caption(
                        f"거래처: **{parsed.get('supplier', '-')}**  |  "
                        f"{od_label}: {parsed.get('order_date', '-')}"
                    )
                else:
                    st.caption(
                        f"거래처: **{parsed.get('supplier', '-')}**  |  "
                        f"{od_label}: {parsed.get('order_date', '-')}  |  "
                        f"{eta_label}: {parsed.get('eta') or '-'}"
                    )
            with info2:
                currencies = ["KRW", "CNY", "USD", "JPY"]
                cur_idx = currencies.index(currency) if currency in currencies else 0
                selected_cur = st.selectbox(
                    "통화", currencies, index=cur_idx,
                    key=f"cur_quick_{file_key}",
                )
                parsed["currency"] = selected_cur
                currency = selected_cur
                if selected_cur != currency:
                    items = add_calc_prices(items, selected_cur)

            # 통계 바
            st1, st2, st3, st4 = st.columns(4)
            st1.metric("총 품목", f"{len(items)}")
            st2.metric("총 수량", f"{total_qty:,}")
            st3.metric("총 금액", f"₩{total_krw:,.0f}")
            st4.metric("이미지", f"{img_count}")

            rate = get_rates().get(currency, 1)
            if currency != "KRW":
                st.caption(f"💱 환율: 1 {currency} = {rate:,.0f}원  |  원단가 ×{get_vendor_multi()} = 업체가  |  원단가 ×{get_online_multi()} = 온라인가")

            # 품목 테이블
            render_order_items_table(items, currency)

            # 연결 건 선택
            all_orders = load_all_orders()
            opposite_type = "인보이스" if doc_type == "발주서" else "발주서"
            linkable = [o for o in all_orders if o.get("doc_type") == opposite_type and not o.get("linked_id")]
            link_options = ["연결 안 함"] + [
                f"{o['id']} · {o.get('supplier', '')} · {o.get('order_date', '')}"
                for o in linkable
            ]
            selected_link = st.selectbox(
                f"🔗 연결할 {opposite_type} 선택 (선택사항)",
                link_options,
                key=f"link_{file_key}",
            )
            linked_id = None
            if selected_link != "연결 안 함":
                linked_id = linkable[link_options.index(selected_link) - 1]["id"]

            # 버튼
            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                if st.button("✅ 바로 등록", key=f"quick_{file_key}", type="primary", use_container_width=True):
                    save_items = add_calc_prices(items, currency)
                    order = {
                        "supplier": parsed.get("supplier", ""),
                        "order_date": parsed.get("order_date"),
                        "eta": parsed.get("eta") or ((parse_date(parsed.get("order_date")) or datetime.now().date()) + timedelta(days=7)).strftime("%Y-%m-%d"),
                        "currency": currency,
                        "items": save_items,
                        "total_amount": total_krw,
                        "status": "확인 대기",
                        "source_file": fname,
                        "notes": parsed.get("notes"),
                        "doc_type": doc_type,
                        "linked_id": linked_id,
                    }
                    order_id = save_order(order)
                    if linked_id:
                        linked_order = load_order(linked_id)
                        if linked_order:
                            linked_order["linked_id"] = order_id
                            update_order(linked_id, linked_order)
                    results[file_key]["done"] = True
                    results[file_key]["order_id"] = order_id
                    results[file_key]["doc_type"] = doc_type
                    results[file_key]["item_count"] = len(items)
                    results[file_key]["img_count"] = img_count
                    st.session_state["upload_results"] = results
                    st.rerun()

            with btn_col2:
                if st.button("✏️ 수정 후 등록", key=f"detail_{file_key}", use_container_width=True):
                    st.session_state[f"expand_{file_key}"] = True
                    st.rerun()

            # ── 수정 모드 ──
            if st.session_state.get(f"expand_{file_key}"):
                st.markdown("---")
                od_lbl = date_label(doc_type, "order_date")
                eta_lbl = date_label(doc_type, "eta")

                ec1, ec2, ec3, ec4 = st.columns(4)
                with ec1:
                    parsed["supplier"] = st.text_input("거래처", value=parsed.get("supplier", ""), key=f"sup_{file_key}")
                with ec2:
                    od = parse_date(parsed.get("order_date"))
                    sel_od = st.date_input(od_lbl, value=od or datetime.now().date(), key=f"od_{file_key}")
                    parsed["order_date"] = sel_od.strftime("%Y-%m-%d")
                with ec3:
                    eta_val = parse_date(parsed.get("eta"))
                    default_eta = eta_val or ((parse_date(parsed.get("order_date")) or datetime.now().date()) + timedelta(days=7))
                    sel_eta = st.date_input(eta_lbl, value=default_eta, key=f"eta_{file_key}")
                    parsed["eta"] = sel_eta.strftime("%Y-%m-%d") if sel_eta else None
                with ec4:
                    currencies = ["KRW", "CNY", "USD", "JPY"]
                    cur_idx = currencies.index(currency) if currency in currencies else 0
                    parsed["currency"] = st.selectbox("통화", currencies, index=cur_idx, key=f"cur_{file_key}")

                edit_cur = parsed.get("currency", "KRW")
                edit_items = add_calc_prices(items, edit_cur)
                edit_rows = []
                for it in edit_items:
                    row = {
                        "원본명": it.get("name", ""),
                        "색상": it.get("color") or "",
                        "내부명": it.get("display_name") or "",
                        "수량": it.get("quantity", 0),
                        f"단가({edit_cur})": it.get("unit_price", 0),
                        "원단가(₩)": it.get("krw_price", 0),
                        "업체가(₩)": it.get("vendor_price", 0),
                        "온라인가(₩)": it.get("online_price", 0),
                        "메모": it.get("memo", ""),
                    }
                    edit_rows.append(row)
                edited_df = st.data_editor(
                    pd.DataFrame(edit_rows),
                    use_container_width=True,
                    hide_index=True,
                    disabled=["원단가(₩)", "업체가(₩)", "온라인가(₩)"],
                    key=f"edit_{file_key}",
                )

                edit_notes = st.text_input(
                    "발주 메모", value=parsed.get("notes") or "",
                    key=f"notes_{file_key}", placeholder="특이사항",
                )

                if st.button("등록", key=f"save_{file_key}", type="primary", use_container_width=True):
                    save_cur = parsed.get("currency", "KRW")
                    price_col = f"단가({save_cur})"
                    new_items = []
                    for i, row in edited_df.iterrows():
                        up = row.get(price_col, 0)
                        krw, vendor, online = calc_prices(up, save_cur)
                        item_dict = {
                            "name": row["원본명"],
                            "color": row["색상"] if row["색상"] else "",
                            "display_name": row["내부명"] if row["내부명"] else "",
                            "quantity": row["수량"],
                            "unit_price": up,
                            "subtotal": row["수량"] * up,
                            "krw_price": krw,
                            "vendor_price": vendor,
                            "online_price": online,
                            "memo": row["메모"] if row["메모"] else "",
                        }
                        if i < len(items) and items[i].get("image"):
                            item_dict["image"] = items[i]["image"]
                        new_items.append(item_dict)
                    order = {
                        "supplier": parsed["supplier"],
                        "order_date": parsed.get("order_date"),
                        "eta": parsed.get("eta") or ((parse_date(parsed.get("order_date")) or datetime.now().date()) + timedelta(days=7)).strftime("%Y-%m-%d"),
                        "currency": save_cur,
                        "items": new_items,
                        "total_amount": sum(it["subtotal"] for it in new_items),
                        "status": "확인 대기",
                        "source_file": fname,
                        "notes": edit_notes if edit_notes else None,
                        "doc_type": doc_type,
                        "linked_id": linked_id,
                    }
                    order_id = save_order(order)
                    if linked_id:
                        linked_order = load_order(linked_id)
                        if linked_order:
                            linked_order["linked_id"] = order_id
                            update_order(linked_id, linked_order)
                    edit_img_count = sum(1 for it in new_items if it.get("image"))
                    results[file_key]["done"] = True
                    results[file_key]["order_id"] = order_id
                    results[file_key]["doc_type"] = doc_type
                    results[file_key]["item_count"] = len(new_items)
                    results[file_key]["img_count"] = edit_img_count
                    st.session_state[f"expand_{file_key}"] = False
                    st.session_state["upload_results"] = results
                    st.rerun()

        if results and not has_pending:
            st.markdown("---")
            st.success("모든 파일이 등록되었습니다!")
            if st.button("새 파일 업로드"):
                st.session_state["upload_results"] = {}
                st.rerun()


# ════════════════════════════════════════════
# 📋 발주 목록
# ════════════════════════════════════════════
elif page == "📋 발주 목록":
    st.title("발주 목록")
    st.caption("발주 내역을 확인하고 관리하세요")

    orders = load_all_orders()
    if not orders:
        st.info("등록된 발주가 없습니다.")
        st.stop()

    col_s, col_f, col_t = st.columns([2, 1, 1])
    with col_s:
        search = st.text_input("검색", placeholder="발주번호, 거래처...", label_visibility="collapsed")
    with col_f:
        sfilter = st.selectbox("상태", ["전체", "확인 대기", "확인 완료", "배송 중", "입고 완료"])
    with col_t:
        tfilter = st.selectbox("유형", ["전체", "발주서", "인보이스"])

    filtered = orders
    if search:
        q = search.lower()
        filtered = [o for o in filtered if q in (o["id"] + o.get("supplier", "")).lower()]
    if sfilter != "전체":
        filtered = [o for o in filtered if o.get("status") == sfilter]
    if tfilter != "전체":
        filtered = [o for o in filtered if o.get("doc_type") == tfilter]

    st.caption(f"{len(filtered)}건")

    # ── 그룹화된 목록 ──
    groups = group_orders(filtered)

    def render_order_edit(o):
        """단일 주문 편집 UI"""
        oid = o["id"]
        doc_type = o.get("doc_type", "발주서")
        status = o.get("status", "확인 대기")
        items = o.get("items", [])
        total_qty = sum(i.get("quantity", 0) for i in items)

        badge_cls = "badge-po" if doc_type == "발주서" else "badge-inv"
        st.markdown(f'<span class="{badge_cls}">{doc_type}</span> **{oid}**', unsafe_allow_html=True)

        od_lbl = date_label(doc_type, "order_date")
        eta_lbl = date_label(doc_type, "eta")

        bc1, bc2, bc3, bc4 = st.columns(4)
        with bc1:
            edit_supplier = st.text_input("거래처", value=o.get("supplier", ""), key=f"sup_{oid}")
        with bc2:
            od = parse_date(o.get("order_date"))
            edit_od = st.date_input(od_lbl, value=od or datetime.now().date(), key=f"od_{oid}")
        with bc3:
            eta = parse_date(o.get("eta"))
            edit_eta = st.date_input(eta_lbl, value=eta or None, key=f"eta_{oid}")
        with bc4:
            statuses = ["확인 대기", "확인 완료", "배송 중", "입고 완료"]
            edit_status = st.selectbox(
                "상태", statuses,
                index=statuses.index(status) if status in statuses else 0,
                key=f"st_{oid}",
            )

        edit_notes = st.text_input(
            "메모", value=o.get("notes") or "", key=f"notes_{oid}",
            placeholder="특이사항",
        )
        st.caption(f"📎 {o.get('source_file', '-')}  |  {total_qty:,}개 · {len(items)}종")

        # 품목 테이블
        edited = None
        if items:
            o_cur = o.get("currency", "KRW")
            rate = get_rates().get(o_cur, 1)
            if o_cur != "KRW":
                st.caption(f"💱 1 {o_cur} = {rate:,.0f}원  |  ×{get_vendor_multi()} 업체가  |  ×{get_online_multi()} 온라인가")

            has_img_list = any(it.get("image") for it in items)
            items_data = []
            for it in items:
                if it.get("krw_price"):
                    krw, vendor, online = it["krw_price"], it["vendor_price"], it["online_price"]
                else:
                    krw, vendor, online = calc_prices(it.get("unit_price", 0), o_cur)
                row = {}
                if has_img_list:
                    row["이미지"] = it.get("image") or ""
                row["원본명"] = it.get("name", "")
                row["색상"] = it.get("color") or ""
                row["내부명"] = it.get("display_name") or ""
                row["수량"] = it.get("quantity", 0)
                row[f"단가({o_cur})"] = it.get("unit_price", 0)
                row["원단가(₩)"] = krw
                row["업체가(₩)"] = vendor
                row["온라인가(₩)"] = online
                row["메모"] = it.get("memo", "")
                items_data.append(row)

            edit_col_config = {
                "원본명": st.column_config.TextColumn("원본명", width="medium"),
                "색상": st.column_config.TextColumn("색상", width="small"),
                "내부명": st.column_config.TextColumn("내부명", width="medium"),
                "수량": st.column_config.NumberColumn("수량", format="%.0f"),
                f"단가({o_cur})": st.column_config.NumberColumn(f"단가({o_cur})", format="%.2f"),
                "원단가(₩)": st.column_config.NumberColumn("원단가(₩)", format="%d"),
                "업체가(₩)": st.column_config.NumberColumn("업체가(₩)", format="%d"),
                "온라인가(₩)": st.column_config.NumberColumn("온라인가(₩)", format="%d"),
                "메모": st.column_config.TextColumn("메모", width="medium"),
            }
            disabled_cols = ["원단가(₩)", "업체가(₩)", "온라인가(₩)"]
            if has_img_list:
                edit_col_config["이미지"] = st.column_config.ImageColumn("이미지", width="small")
                disabled_cols.append("이미지")

            edited = st.data_editor(
                pd.DataFrame(items_data),
                use_container_width=True,
                hide_index=True,
                disabled=disabled_cols,
                column_config=edit_col_config,
                key=f"edit_{oid}",
            )

        return {
            "supplier": edit_supplier,
            "order_date": edit_od,
            "eta": edit_eta,
            "status": edit_status,
            "notes": edit_notes,
            "edited_df": edited,
            "items": items,
        }

    for group in groups:
        if len(group) == 1:
            # ── 단독 건 ──
            o = group[0]
            oid = o["id"]
            doc_type = o.get("doc_type", "발주서")
            d_icon = "📋" if doc_type == "발주서" else "📄"
            status = o.get("status", "확인 대기")

            header = f"{d_icon} **[{doc_type}]** {oid}  ·  {o.get('supplier', '')}  ·  {fmt_amount(o.get('total_amount'), o.get('currency'))}  ·  {status}"
            with st.expander(header):
                edit_data = render_order_edit(o)
                st.markdown("---")
                save_col, del_col = st.columns([3, 1])
                with save_col:
                    if st.button("💾 저장", key=f"save_all_{oid}", type="primary", use_container_width=True):
                        save_cur = o.get("currency", "KRW")
                        price_col = f"단가({save_cur})"
                        new_items = []
                        if edit_data["items"] and edit_data["edited_df"] is not None:
                            for i, row in edit_data["edited_df"].iterrows():
                                up = row.get(price_col, 0)
                                krw, vendor, online = calc_prices(up, save_cur)
                                item_dict = {
                                    "name": row["원본명"],
                                    "color": row["색상"] if row["색상"] else "",
                                    "display_name": row["내부명"] if row["내부명"] else "",
                                    "quantity": row["수량"],
                                    "unit_price": up,
                                    "subtotal": row["수량"] * up,
                                    "krw_price": krw,
                                    "vendor_price": vendor,
                                    "online_price": online,
                                    "memo": row["메모"] if row["메모"] else "",
                                }
                                if i < len(edit_data["items"]) and edit_data["items"][i].get("image"):
                                    item_dict["image"] = edit_data["items"][i]["image"]
                                new_items.append(item_dict)
                        o_copy = dict(o)
                        o_copy["supplier"] = edit_data["supplier"]
                        o_copy["order_date"] = edit_data["order_date"].strftime("%Y-%m-%d")
                        o_copy["eta"] = edit_data["eta"].strftime("%Y-%m-%d") if edit_data["eta"] else None
                        o_copy["status"] = edit_data["status"]
                        o_copy["notes"] = edit_data["notes"] if edit_data["notes"] else None
                        o_copy["items"] = new_items if new_items else edit_data["items"]
                        o_copy["total_amount"] = sum(it.get("subtotal", 0) for it in o_copy["items"])
                        update_order(oid, o_copy)
                        st.success("저장 완료!")
                        st.rerun()
                with del_col:
                    if st.button("🗑️ 삭제", key=f"del_{oid}", use_container_width=True):
                        delete_order(oid)
                        st.rerun()

        else:
            # ── 연결된 건 (발주서 + 인보이스) ──
            po = group[0]
            inv = group[1]
            supplier = po.get("supplier") or inv.get("supplier", "")

            header = f"🔗 **[발주서+인보이스]** {po['id']} + {inv['id']}  ·  {supplier}"
            with st.expander(header):
                # 발주서 탭 / 인보이스 탭
                tab_po, tab_inv = st.tabs(["📋 발주서", "📄 인보이스"])

                with tab_po:
                    edit_po = render_order_edit(po)
                    st.markdown("---")
                    sc1, dc1 = st.columns([3, 1])
                    with sc1:
                        if st.button("💾 저장", key=f"save_all_{po['id']}", type="primary", use_container_width=True):
                            save_cur = po.get("currency", "KRW")
                            price_col = f"단가({save_cur})"
                            new_items = []
                            if edit_po["items"] and edit_po["edited_df"] is not None:
                                for i, row in edit_po["edited_df"].iterrows():
                                    up = row.get(price_col, 0)
                                    krw, vendor, online = calc_prices(up, save_cur)
                                    item_dict = {
                                        "name": row["원본명"],
                                        "color": row["색상"] if row["색상"] else "",
                                        "display_name": row["내부명"] if row["내부명"] else "",
                                        "quantity": row["수량"],
                                        "unit_price": up,
                                        "subtotal": row["수량"] * up,
                                        "krw_price": krw,
                                        "vendor_price": vendor,
                                        "online_price": online,
                                        "memo": row["메모"] if row["메모"] else "",
                                    }
                                    if i < len(edit_po["items"]) and edit_po["items"][i].get("image"):
                                        item_dict["image"] = edit_po["items"][i]["image"]
                                    new_items.append(item_dict)
                            o_copy = dict(po)
                            o_copy["supplier"] = edit_po["supplier"]
                            o_copy["order_date"] = edit_po["order_date"].strftime("%Y-%m-%d")
                            o_copy["eta"] = edit_po["eta"].strftime("%Y-%m-%d") if edit_po["eta"] else None
                            o_copy["status"] = edit_po["status"]
                            o_copy["notes"] = edit_po["notes"] if edit_po["notes"] else None
                            o_copy["items"] = new_items if new_items else edit_po["items"]
                            o_copy["total_amount"] = sum(it.get("subtotal", 0) for it in o_copy["items"])
                            update_order(po["id"], o_copy)
                            st.success("저장 완료!")
                            st.rerun()
                    with dc1:
                        if st.button("🗑️ 삭제", key=f"del_{po['id']}", use_container_width=True):
                            delete_order(po["id"])
                            st.rerun()

                with tab_inv:
                    edit_inv = render_order_edit(inv)
                    st.markdown("---")
                    sc2, dc2 = st.columns([3, 1])
                    with sc2:
                        if st.button("💾 저장", key=f"save_all_{inv['id']}", type="primary", use_container_width=True):
                            save_cur = inv.get("currency", "KRW")
                            price_col = f"단가({save_cur})"
                            new_items = []
                            if edit_inv["items"] and edit_inv["edited_df"] is not None:
                                for i, row in edit_inv["edited_df"].iterrows():
                                    up = row.get(price_col, 0)
                                    krw, vendor, online = calc_prices(up, save_cur)
                                    item_dict = {
                                        "name": row["원본명"],
                                        "color": row["색상"] if row["색상"] else "",
                                        "display_name": row["내부명"] if row["내부명"] else "",
                                        "quantity": row["수량"],
                                        "unit_price": up,
                                        "subtotal": row["수량"] * up,
                                        "krw_price": krw,
                                        "vendor_price": vendor,
                                        "online_price": online,
                                        "memo": row["메모"] if row["메모"] else "",
                                    }
                                    if i < len(edit_inv["items"]) and edit_inv["items"][i].get("image"):
                                        item_dict["image"] = edit_inv["items"][i]["image"]
                                    new_items.append(item_dict)
                            o_copy = dict(inv)
                            o_copy["supplier"] = edit_inv["supplier"]
                            o_copy["order_date"] = edit_inv["order_date"].strftime("%Y-%m-%d")
                            o_copy["eta"] = edit_inv["eta"].strftime("%Y-%m-%d") if edit_inv["eta"] else None
                            o_copy["status"] = edit_inv["status"]
                            o_copy["notes"] = edit_inv["notes"] if edit_inv["notes"] else None
                            o_copy["items"] = new_items if new_items else edit_inv["items"]
                            o_copy["total_amount"] = sum(it.get("subtotal", 0) for it in o_copy["items"])
                            update_order(inv["id"], o_copy)
                            st.success("저장 완료!")
                            st.rerun()
                    with dc2:
                        if st.button("🗑️ 삭제", key=f"del_{inv['id']}", use_container_width=True):
                            delete_order(inv["id"])
                            st.rerun()

    # 엑셀 다운로드
    st.markdown("---")
    if orders:
        summary_data = []
        all_items_data = []
        for o in orders:
            o_doc_type = o.get("doc_type", "발주서")
            od_lbl = date_label(o_doc_type, "order_date")
            eta_lbl = date_label(o_doc_type, "eta")
            summary_data.append({
                "발주번호": o["id"],
                "유형": o_doc_type,
                "거래처": o.get("supplier"),
                od_lbl: o.get("order_date"),
                eta_lbl: o.get("eta"),
                "통화": o.get("currency"),
                "총금액": o.get("total_amount"),
                "상태": o.get("status"),
                "연결": o.get("linked_id") or "",
            })
            o_cur = o.get("currency", "KRW")
            for i in o.get("items", []):
                if i.get("krw_price"):
                    krw, vendor, online = i["krw_price"], i["vendor_price"], i["online_price"]
                else:
                    krw, vendor, online = calc_prices(i.get("unit_price", 0), o_cur)
                all_items_data.append({
                    "발주번호": o["id"],
                    "유형": o_doc_type,
                    "원본명": i.get("name"),
                    "색상": i.get("color") or "",
                    "내부명": i.get("display_name") or "",
                    "수량": i.get("quantity"),
                    f"단가({o_cur})": i.get("unit_price"),
                    "원단가(₩)": krw,
                    "업체가(₩)": vendor,
                    "온라인가(₩)": online,
                    "메모": i.get("memo", ""),
                })

        buf = BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            pd.DataFrame(summary_data).to_excel(writer, sheet_name="발주요약", index=False)
            if all_items_data:
                pd.DataFrame(all_items_data).to_excel(writer, sheet_name="품목상세", index=False)

        st.download_button(
            "📥 엑셀 다운로드",
            data=buf.getvalue(),
            file_name=f"발주현황_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


# ════════════════════════════════════════════
# 🔧 관리
# ════════════════════════════════════════════
elif page == "🔧 관리":
    st.title("관리")

    st.markdown("#### API 상태")
    if API_KEY:
        st.success(f"API 키 설정됨 (···{API_KEY[-6:]})")
        st.caption("Streamlit Cloud Secrets에서 관리됩니다.")
    else:
        st.error("API 키 미설정")

    st.markdown("---")
    st.markdown("#### 💱 가격 계산 설정")
    st.caption("환율, 배수, 반올림 단위를 조정하면 모든 페이지에 즉시 반영됩니다.")

    rates = get_rates()
    rc1, rc2, rc3 = st.columns(3)
    with rc1:
        new_cny = st.number_input("CNY (위안) 환율", value=float(rates.get("CNY", 220)), step=10.0, format="%.0f", key="set_cny")
    with rc2:
        new_usd = st.number_input("USD (달러) 환율", value=float(rates.get("USD", 1500)), step=50.0, format="%.0f", key="set_usd")
    with rc3:
        new_jpy = st.number_input("JPY (엔) 환율", value=float(rates.get("JPY", 10)), step=1.0, format="%.0f", key="set_jpy")

    mc1, mc2, mc3 = st.columns(3)
    with mc1:
        new_vendor = st.number_input("업체가 배수", value=float(get_vendor_multi()), step=0.1, format="%.1f", key="set_vendor")
    with mc2:
        new_online = st.number_input("온라인가 배수", value=float(get_online_multi()), step=0.1, format="%.1f", key="set_online")
    with mc3:
        round_options = {100: "100원 단위", 10: "10원 단위", 1000: "1,000원 단위"}
        current_round = get_round_unit()
        round_keys = list(round_options.keys())
        new_round = st.selectbox(
            "반올림 단위",
            round_keys,
            index=round_keys.index(current_round) if current_round in round_keys else 0,
            format_func=lambda x: round_options[x],
            key="set_round",
        )

    if st.button("설정 저장", key="save_settings", type="primary", use_container_width=True):
        st.session_state["exchange_rates"] = {"CNY": new_cny, "USD": new_usd, "JPY": new_jpy, "KRW": 1}
        st.session_state["vendor_multi"] = new_vendor
        st.session_state["online_multi"] = new_online
        st.session_state["round_unit"] = new_round
        st.success("설정이 저장되었습니다!")

    st.caption(f"현재 설정 — CNY ×{rates.get('CNY', 220):.0f} | USD ×{rates.get('USD', 1500):.0f} | JPY ×{rates.get('JPY', 10):.0f} | 업체가 ×{get_vendor_multi()} | 온라인가 ×{get_online_multi()} | {round_options.get(get_round_unit(), '100원 단위')}")

    st.markdown("---")
    st.markdown("#### 데이터 백업")
    st.caption("정기적으로 백업을 받아두세요.")

    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "JSON 백업",
            data=export_all_json(),
            file_name=f"orderflow_{datetime.now().strftime('%Y%m%d')}.json",
            mime="application/json",
            use_container_width=True,
        )
    with col2:
        backup = st.file_uploader("백업 복원", type=["json"], label_visibility="collapsed")
        if backup:
            try:
                data = _json.loads(backup.read())
                added = import_orders(data.get("orders", []))
                st.success(f"{added}건 복원 완료")
            except Exception as e:
                st.error(f"오류: {e}")

    st.markdown("---")
    st.markdown("#### 데이터 초기화")
    if st.button("전체 삭제"):
        if st.session_state.get("confirm_delete"):
            from pathlib import Path
            p = Path("data/orders.json")
            if p.exists():
                p.unlink()
            st.session_state["confirm_delete"] = False
            st.rerun()
        else:
            st.session_state["confirm_delete"] = True
            st.warning("한 번 더 누르면 삭제됩니다.")
