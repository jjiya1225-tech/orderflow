"""
OrderFlow - AI 발주 관리 시스템 v3
팀원 중심 UI: 입고일 · 품목 · 수량
"""

import streamlit as st
import pandas as pd
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
# CSS (간결하게)
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

/* 캘린더 */
.cal-grid {
    display: grid;
    grid-template-columns: repeat(7, 1fr);
    gap: 2px;
    margin-top: 8px;
}
.cal-header {
    text-align: center;
    font-size: 11px;
    font-weight: 600;
    color: #86868b;
    padding: 8px 0;
}
.cal-day {
    text-align: center;
    padding: 8px 4px;
    border-radius: 10px;
    font-size: 13px;
    min-height: 44px;
}
.cal-day.today { background: #f5f5f7; font-weight: 700; }
.cal-day.has-order { background: #e8f4fd; }
.cal-day.has-order.urgent { background: #fff5f5; }
.cal-dot {
    width: 6px; height: 6px;
    border-radius: 50%;
    background: #0071e3;
    margin: 4px auto 0;
}
.cal-day.urgent .cal-dot { background: #e53e3e; }
.cal-day.empty { color: #d2d2d7; }
</style>
""", unsafe_allow_html=True)


def fmt_amount(amt, cur="KRW"):
    if not amt:
        return "-"
    sym = {"KRW": "₩", "CNY": "¥", "USD": "$", "JPY": "¥"}.get(cur, "")
    return f"{sym}{amt:,.0f}"


# ════════════════════════════════════════════
# 가격 자동 계산 (설정값은 session_state에서 관리)
# ════════════════════════════════════════════
DEFAULT_RATES = {"CNY": 220, "USD": 1500, "JPY": 10, "KRW": 1}
DEFAULT_VENDOR_MULTI = 2
DEFAULT_ONLINE_MULTI = 3
DEFAULT_ROUND_UNIT = 100

# session_state에 설정 초기화
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
    """반올림 (단위 설정 반영)"""
    if unit is None:
        unit = get_round_unit()
    return int((v / unit) + 0.5) * unit


def calc_prices(unit_price, currency):
    """외화 단가 → 원단가, 업체가, 온라인가 자동 계산"""
    rate = get_rates().get(currency, 1)
    krw = round_price(unit_price * rate)
    vendor = round_price(krw * get_vendor_multi())
    online = round_price(krw * get_online_multi())
    return krw, vendor, online


def add_calc_prices(items, currency):
    """items 리스트에 원단가/업체가/온라인가 필드 추가"""
    for it in items:
        price = it.get("unit_price", 0)
        krw, vendor, online = calc_prices(price, currency)
        it["krw_price"] = krw
        it["vendor_price"] = vendor
        it["online_price"] = online
    return items


def parse_date(s):
    """다양한 날짜 문자열을 date 객체로 변환"""
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

        # ── 입고 캘린더 ──
        st.subheader("📅 입고 캘린더")

        cal_col1, cal_col2 = st.columns([3, 1])
        with cal_col2:
            month_offset = st.selectbox(
                "월 선택",
                [0, 1, 2],
                format_func=lambda x: (now + timedelta(days=30 * x)).strftime("%Y년 %m월"),
                label_visibility="collapsed",
            )

        target_date = now + timedelta(days=30 * month_offset)
        year, month = target_date.year, target_date.month
        first_weekday, num_days = monthrange(year, month)

        # 해당 월 입고 예정 수집
        eta_map = {}
        for o in orders:
            if o.get("eta") and o.get("status") != "입고 완료":
                try:
                    eta_dt = datetime.strptime(o["eta"], "%Y-%m-%d")
                    if eta_dt.year == year and eta_dt.month == month:
                        day = eta_dt.day
                        if day not in eta_map:
                            eta_map[day] = []
                        eta_map[day].append(o)
                except Exception:
                    pass

        # 캘린더 HTML (단순 그리드만 — 깨지지 않도록)
        weekdays = ["월", "화", "수", "목", "금", "토", "일"]
        cal_html = '<div class="cal-grid">'
        for w in weekdays:
            cal_html += f'<div class="cal-header">{w}</div>'
        for _ in range(first_weekday):
            cal_html += '<div class="cal-day empty"></div>'
        for day in range(1, num_days + 1):
            cls = "cal-day"
            dot = ""
            if day == now.day and month == now.month and year == now.year:
                cls += " today"
            if day in eta_map:
                is_past = datetime(year, month, day) < datetime(now.year, now.month, now.day)
                cls += " has-order"
                if is_past:
                    cls += " urgent"
                dot = '<div class="cal-dot"></div>'
            cal_html += f'<div class="{cls}">{day}{dot}</div>'
        cal_html += "</div>"

        with cal_col1:
            st.markdown(cal_html, unsafe_allow_html=True)

        # ── 입고 예정 리스트 (Streamlit 네이티브) ──
        if eta_map:
            st.markdown("")
            for day in sorted(eta_map.keys()):
                day_date = f"{year}-{month:02d}-{day:02d}"
                is_past = day_date < today_str
                for o in eta_map[day]:
                    items = o.get("items", [])
                    total_qty = sum(i.get("quantity", 0) for i in items)

                    # 지연 여부 표시
                    if is_past:
                        days_late = (now - datetime.strptime(day_date, "%Y-%m-%d")).days
                        label = f"🔴  {month}/{day} — {o.get('supplier', '')}  ·  **{days_late}일 지연**"
                    else:
                        label = f"🔵  {month}/{day} — {o.get('supplier', '')}"

                    with st.expander(label, expanded=is_past):
                        # 품목 + 색상 + 수량 테이블
                        rows = []
                        for it in items:
                            display = it.get("display_name") or ""
                            name = it.get("name", "")
                            show_name = display if display else name
                            color = it.get("color") or ""
                            if color:
                                show_name = f"{show_name} ({color})"
                            rows.append({
                                "품목": show_name,
                                "수량": it.get("quantity", 0),
                            })
                        df = pd.DataFrame(rows)
                        st.dataframe(df, use_container_width=True, hide_index=True)
                        st.caption(f"총 {total_qty:,}개  ·  {fmt_amount(o.get('total_amount'), o.get('currency'))}")

        st.markdown("---")

        # ── 전체 발주 목록 (간결 테이블) ──
        st.subheader("전체 발주")

        status_filter = st.selectbox(
            "필터",
            ["전체", "확인 대기", "확인 완료", "배송 중", "입고 완료"],
            label_visibility="collapsed",
        )
        filtered = orders if status_filter == "전체" else [o for o in orders if o.get("status") == status_filter]

        for o in filtered[:20]:
            items = o.get("items", [])
            total_qty = sum(i.get("quantity", 0) for i in items)
            status = o.get("status", "확인 대기")

            header = f"{o['id']}  ·  **{o.get('supplier', '')}**  ·  {fmt_amount(o.get('total_amount'), o.get('currency'))}  ·  {status}"

            with st.expander(header):
                st.caption(
                    f"발주일: {o.get('order_date', '-')}  |  "
                    f"입고예정: {o.get('eta') or '-'}  |  "
                    f"{total_qty:,}개 · {len(items)}종"
                )
                # 품목 테이블 (인보이스 변환기 스타일)
                o_cur = o.get("currency", "KRW")
                has_img = any(it.get("image") for it in items)
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
                        krw, vendor, online = calc_prices(it.get("unit_price", 0), o_cur)
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
                dash_col_config = {}
                if has_img:
                    dash_col_config["이미지"] = st.column_config.ImageColumn("이미지", width="small")
                st.dataframe(df, use_container_width=True, hide_index=True, column_config=dash_col_config)

                if o.get("notes"):
                    st.info(f"📝 {o['notes']}")


# ════════════════════════════════════════════
# ⬆️ 발주서 업로드
# ════════════════════════════════════════════
elif page == "⬆️ 발주서 업로드":
    st.title("발주서 업로드")
    st.caption("파일을 올리면 AI가 자동 분석 후 바로 등록합니다  ·  여러 파일도 한번에 가능")

    if not API_KEY:
        st.error("Claude API 키가 설정되지 않았습니다. 관리자에게 문의하세요.")
        st.stop()

    uploaded_files = st.file_uploader(
        "발주서 파일 선택 (여러 개 가능)",
        type=["xlsx", "xls", "csv", "pdf", "jpg", "jpeg", "png", "webp"],
        help="Excel, PDF, 이미지 파일 지원",
        accept_multiple_files=True,
    )

    if uploaded_files:
        # 처리 상태 초기화
        if "upload_results" not in st.session_state:
            st.session_state["upload_results"] = {}

        results = st.session_state["upload_results"]

        # ── 각 파일 자동 분석 + 등록 ──
        for uploaded in uploaded_files:
            file_key = f"{uploaded.name}_{uploaded.size}"

            # 이미 처리 완료된 파일은 건너뛰기
            if file_key in results and results[file_key].get("done"):
                continue

            # 분석 시작
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

            # 오류 발생한 파일
            if res.get("error"):
                st.error(f"**{fname}** — 분석 실패: {res['error']}")
                continue

            # 이미 등록 완료
            if res.get("done") and res.get("order_id"):
                st.success(f"**{fname}** → {res.get('order_id')} 등록 완료")
                continue

            # 분석 완료, 등록 대기 중
            parsed = res.get("parsed")
            if not parsed:
                continue

            has_pending = True
            items = parsed.get("items", [])
            currency = parsed.get("currency", "KRW")
            # 가격 자동 계산
            items = add_calc_prices(items, currency)

            total_qty = sum(i.get("quantity", 0) for i in items)
            total_krw = sum(i.get("quantity", 0) * i.get("krw_price", 0) for i in items)
            img_count = sum(1 for i in items if i.get("image"))

            # 요약 카드
            st.markdown("---")
            st.markdown(f"#### {fname}")

            # 거래처 + 통화 선택
            info1, info2 = st.columns([3, 1])
            with info1:
                st.caption(
                    f"거래처: **{parsed.get('supplier', '-')}**  |  "
                    f"발주일: {parsed.get('order_date', '-')}  |  "
                    f"입고예정: {parsed.get('eta') or '-'}"
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
                # 통화 변경 시 재계산
                if selected_cur != currency:
                    items = add_calc_prices(items, selected_cur)

            # 통계 바 (인보이스 변환기 스타일)
            st1, st2, st3, st4 = st.columns(4)
            st1.metric("총 품목", f"{len(items)}")
            st2.metric("총 수량", f"{total_qty:,}")
            st3.metric("총 금액", f"₩{total_krw:,.0f}")
            st4.metric("이미지", f"{img_count}")

            # 환율 정보
            rate = get_rates().get(currency, 1)
            if currency != "KRW":
                st.caption(f"💱 환율: 1 {currency} = {rate:,.0f}원  |  원단가 ×{get_vendor_multi()} = 업체가  |  원단가 ×{get_online_multi()} = 온라인가")

            # 품목 테이블 (인보이스 변환기 스타일: 이미지, 제품명, 수량, 단가, 업체가, 온라인가, 총금액)
            has_images = any(it.get("image") for it in items)
            rows = []
            for it in items:
                name = it.get("name", "")
                color = it.get("color") or ""
                show = f"{name} ({color})" if color else name
                qty = it.get("quantity", 0)
                krw = it.get("krw_price", 0)
                row = {}
                if has_images:
                    row["이미지"] = it.get("image") or ""
                row["제품명"] = show
                row["수량"] = qty
                row["단가"] = f"₩{krw:,.0f}"
                row["업체가"] = f"₩{it.get('vendor_price', 0):,.0f}"
                row["온라인가"] = f"₩{it.get('online_price', 0):,.0f}"
                row["총금액"] = f"₩{qty * krw:,.0f}"
                rows.append(row)
            col_config = {}
            if has_images:
                col_config["이미지"] = st.column_config.ImageColumn("이미지", width="small")
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, column_config=col_config)

            # 버튼: 바로 등록 / 수정 후 등록
            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                if st.button("✅ 바로 등록", key=f"quick_{file_key}", type="primary", use_container_width=True):
                    save_items = add_calc_prices(items, currency)
                    order = {
                        "supplier": parsed.get("supplier", ""),
                        "order_date": parsed.get("order_date"),
                        "eta": parsed.get("eta") or None,
                        "currency": currency,
                        "items": save_items,
                        "total_amount": total_amt,
                        "status": "확인 대기",
                        "source_file": fname,
                        "notes": parsed.get("notes"),
                    }
                    order_id = save_order(order)
                    results[file_key]["done"] = True
                    results[file_key]["order_id"] = order_id
                    st.session_state["upload_results"] = results
                    st.rerun()

            with btn_col2:
                if st.button("✏️ 수정 후 등록", key=f"detail_{file_key}", use_container_width=True):
                    st.session_state[f"expand_{file_key}"] = True
                    st.rerun()

            # ── 수정 모드 (펼침) ──
            if st.session_state.get(f"expand_{file_key}"):
                st.markdown("---")

                ec1, ec2, ec3, ec4 = st.columns(4)
                with ec1:
                    parsed["supplier"] = st.text_input("거래처", value=parsed.get("supplier", ""), key=f"sup_{file_key}")
                with ec2:
                    od = parse_date(parsed.get("order_date"))
                    sel_od = st.date_input("발주일", value=od or datetime.now().date(), key=f"od_{file_key}")
                    parsed["order_date"] = sel_od.strftime("%Y-%m-%d")
                with ec3:
                    eta_val = parse_date(parsed.get("eta"))
                    sel_eta = st.date_input("입고예정일", value=eta_val or None, key=f"eta_{file_key}")
                    parsed["eta"] = sel_eta.strftime("%Y-%m-%d") if sel_eta else None
                with ec4:
                    currencies = ["KRW", "CNY", "USD", "JPY"]
                    cur_idx = currencies.index(currency) if currency in currencies else 0
                    parsed["currency"] = st.selectbox("통화", currencies, index=cur_idx, key=f"cur_{file_key}")

                # 품목 테이블 (수정 가능 + 가격 계산)
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
                        # 이미지 유지
                        if i < len(items) and items[i].get("image"):
                            item_dict["image"] = items[i]["image"]
                        new_items.append(item_dict)
                    order = {
                        "supplier": parsed["supplier"],
                        "order_date": parsed.get("order_date"),
                        "eta": parsed.get("eta") or None,
                        "currency": save_cur,
                        "items": new_items,
                        "total_amount": sum(it["subtotal"] for it in new_items),
                        "status": "확인 대기",
                        "source_file": fname,
                        "notes": edit_notes if edit_notes else None,
                    }
                    order_id = save_order(order)
                    results[file_key]["done"] = True
                    results[file_key]["order_id"] = order_id
                    st.session_state[f"expand_{file_key}"] = False
                    st.session_state["upload_results"] = results
                    st.rerun()

        # 전체 등록 완료 시 초기화 안내
        if results and not has_pending:
            st.markdown("---")
            st.success("모든 발주서가 등록되었습니다!")
            if st.button("새 발주서 업로드"):
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

    col_s, col_f = st.columns([2, 1])
    with col_s:
        search = st.text_input("검색", placeholder="발주번호, 거래처...", label_visibility="collapsed")
    with col_f:
        sfilter = st.selectbox("상태", ["전체", "확인 대기", "확인 완료", "배송 중", "입고 완료"])

    filtered = orders
    if search:
        q = search.lower()
        filtered = [o for o in filtered if q in (o["id"] + o.get("supplier", "")).lower()]
    if sfilter != "전체":
        filtered = [o for o in filtered if o.get("status") == sfilter]

    st.caption(f"{len(filtered)}건")

    for o in filtered:
        oid = o["id"]
        status = o.get("status", "확인 대기")
        items = o.get("items", [])
        total_qty = sum(i.get("quantity", 0) for i in items)

        header = f"{oid}  ·  **{o.get('supplier', '')}**  ·  {fmt_amount(o.get('total_amount'), o.get('currency'))}  ·  {status}"

        with st.expander(header):

            # ── 기본 정보 수정 ──
            st.markdown("**기본 정보**")
            bc1, bc2, bc3, bc4 = st.columns(4)
            with bc1:
                edit_supplier = st.text_input(
                    "거래처", value=o.get("supplier", ""), key=f"sup_{oid}",
                )
            with bc2:
                od = parse_date(o.get("order_date"))
                edit_od = st.date_input(
                    "발주일", value=od or datetime.now().date(), key=f"od_{oid}",
                )
            with bc3:
                eta = parse_date(o.get("eta"))
                edit_eta = st.date_input(
                    "입고예정일", value=eta or None, key=f"eta_{oid}",
                )
            with bc4:
                statuses = ["확인 대기", "확인 완료", "배송 중", "입고 완료"]
                edit_status = st.selectbox(
                    "상태", statuses,
                    index=statuses.index(status) if status in statuses else 0,
                    key=f"st_{oid}",
                )

            edit_notes = st.text_input(
                "발주 메모", value=o.get("notes") or "", key=f"notes_{oid}",
                placeholder="이 발주 건에 대한 메모",
            )

            st.caption(f"📎 {o.get('source_file', '-')}  |  {total_qty:,}개 · {len(items)}종")

            st.markdown("---")

            # ── 품목 테이블 (전체 수정 가능 + 가격 계산) ──
            if items:
                o_cur = o.get("currency", "KRW")
                rate = get_rates().get(o_cur, 1)
                if o_cur != "KRW":
                    st.caption(f"💱 환율: 1 {o_cur} = {rate:,.0f}원  |  원단가 ×{get_vendor_multi()} = 업체가  |  원단가 ×{get_online_multi()} = 온라인가")
                st.markdown("**품목 상세**")

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

            st.markdown("---")

            # ── 저장 / 삭제 버튼 ──
            save_col, del_col = st.columns([3, 1])
            with save_col:
                if st.button("💾 저장", key=f"save_all_{oid}", type="primary", use_container_width=True):
                    # 품목 데이터 수집 + 가격 재계산
                    save_cur = o.get("currency", "KRW")
                    price_col = f"단가({save_cur})"
                    new_items = []
                    if items:
                        for i, row in edited.iterrows():
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
                            # 기존 이미지 유지
                            if i < len(items) and items[i].get("image"):
                                item_dict["image"] = items[i]["image"]
                            new_items.append(item_dict)
                    # 전체 주문 업데이트
                    o_copy = dict(o)
                    o_copy["supplier"] = edit_supplier
                    o_copy["order_date"] = edit_od.strftime("%Y-%m-%d")
                    o_copy["eta"] = edit_eta.strftime("%Y-%m-%d") if edit_eta else None
                    o_copy["status"] = edit_status
                    o_copy["notes"] = edit_notes if edit_notes else None
                    o_copy["items"] = new_items if new_items else items
                    o_copy["total_amount"] = sum(it.get("subtotal", 0) for it in o_copy["items"])
                    update_order(oid, o_copy)
                    st.success("저장 완료!")
                    st.rerun()

            with del_col:
                if st.button("🗑️ 삭제", key=f"del_{oid}", use_container_width=True):
                    delete_order(oid)
                    st.rerun()

    # 엑셀 다운로드
    st.markdown("---")
    if orders:
        summary_data = []
        all_items_data = []
        for o in orders:
            summary_data.append({
                "발주번호": o["id"],
                "거래처": o.get("supplier"),
                "발주일": o.get("order_date"),
                "입고예정일": o.get("eta"),
                "통화": o.get("currency"),
                "총금액": o.get("total_amount"),
                "상태": o.get("status"),
            })
            o_cur = o.get("currency", "KRW")
            for i in o.get("items", []):
                if i.get("krw_price"):
                    krw, vendor, online = i["krw_price"], i["vendor_price"], i["online_price"]
                else:
                    krw, vendor, online = calc_prices(i.get("unit_price", 0), o_cur)
                all_items_data.append({
                    "발주번호": o["id"],
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
            import json
            try:
                data = json.loads(backup.read())
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
