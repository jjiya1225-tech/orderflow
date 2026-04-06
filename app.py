"""
OrderFlow - AI 발주 관리 시스템 v2
Apple-inspired minimal UI
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
# Apple-inspired CSS
# ════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Noto+Sans+KR:wght@300;400;500;600;700&display=swap');
html, body, [class*="css"] {
    font-family: 'Inter', 'Noto Sans KR', -apple-system, BlinkMacSystemFont, sans-serif;
    -webkit-font-smoothing: antialiased;
}

/* 배경 */
.stApp { background: #fafafa; }
.block-container { padding-top: 1.2rem; max-width: 1000px; }

/* 사이드바 */
[data-testid="stSidebar"] {
    background: #ffffff;
    border-right: 1px solid #f0f0f0;
}
[data-testid="stSidebar"] [data-testid="stMarkdown"] { color: #1d1d1f; }

/* 메트릭 */
[data-testid="stMetric"] {
    background: #ffffff;
    border: 1px solid #f0f0f0;
    border-radius: 16px;
    padding: 20px 22px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.03);
    transition: all 0.2s ease;
}
[data-testid="stMetric"]:hover {
    box-shadow: 0 4px 12px rgba(0,0,0,0.06);
    transform: translateY(-1px);
}
[data-testid="stMetricLabel"] { font-size: 12px; font-weight: 500; color: #86868b; letter-spacing: 0.3px; }
[data-testid="stMetricValue"] { font-size: 30px; font-weight: 700; color: #1d1d1f; letter-spacing: -0.5px; }

/* 버튼 */
.stButton > button {
    border-radius: 12px;
    font-weight: 500;
    font-size: 14px;
    padding: 8px 20px;
    transition: all 0.2s ease;
    border: 1px solid #d2d2d7;
}
.stButton > button:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
.stButton > button[kind="primary"] {
    background: #0071e3;
    border-color: #0071e3;
    color: white;
    border-radius: 12px;
}
.stButton > button[kind="primary"]:hover { background: #0077ED; }

/* 입력 필드 */
.stTextInput > div > div > input,
.stSelectbox > div > div > div,
.stTextArea > div > div > textarea {
    border-radius: 10px;
    border-color: #d2d2d7;
    font-size: 14px;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
    border-color: #0071e3;
    box-shadow: 0 0 0 3px rgba(0,113,227,0.12);
}

/* 데이터프레임 */
.stDataFrame { border-radius: 12px; overflow: hidden; }

/* Expander */
div[data-testid="stExpander"] {
    border: 1px solid #f0f0f0;
    border-radius: 14px;
    background: white;
    box-shadow: 0 1px 4px rgba(0,0,0,0.02);
}

/* 구분선 */
hr { border-color: #f0f0f0 !important; }

/* 파일 업로더 */
[data-testid="stFileUploader"] {
    border-radius: 14px;
}

/* 알림 */
.stSuccess, .stInfo, .stWarning, .stError {
    border-radius: 12px;
}

/* 커스텀 카드 */
.of-card {
    background: #ffffff;
    border: 1px solid #f0f0f0;
    border-radius: 16px;
    padding: 20px 22px;
    margin-bottom: 12px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.02);
    transition: all 0.2s ease;
}
.of-card:hover {
    box-shadow: 0 4px 16px rgba(0,0,0,0.06);
}

/* 긴급 카드 */
.of-urgent {
    background: #fff5f5;
    border: 1px solid #fed7d7;
    border-left: 4px solid #e53e3e;
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
    position: relative;
}
.cal-day.today { background: #f5f5f7; font-weight: 700; }
.cal-day.has-order { background: #e8f4fd; cursor: pointer; }
.cal-day.has-order.urgent { background: #fff5f5; }
.cal-day .cal-dot {
    width: 6px; height: 6px;
    border-radius: 50%;
    background: #0071e3;
    margin: 4px auto 0;
}
.cal-day.urgent .cal-dot { background: #e53e3e; }
.cal-day.empty { color: #d2d2d7; }

/* 상태 뱃지 */
.of-badge {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 500;
}

/* 타이틀 */
.of-title {
    font-size: 28px;
    font-weight: 700;
    color: #1d1d1f;
    letter-spacing: -0.5px;
    margin-bottom: 4px;
}
.of-subtitle {
    font-size: 14px;
    color: #86868b;
    margin-bottom: 24px;
}
</style>
""", unsafe_allow_html=True)


def fmt_amount(amt, cur="KRW"):
    if not amt: return "-"
    sym = {"KRW": "₩", "CNY": "¥", "USD": "$", "JPY": "¥"}.get(cur, "")
    return f"{sym}{amt:,.0f}"

def status_color(s):
    return {"확인 대기": ("#b45309", "#fef3c7"), "확인 완료": ("#047857", "#d1fae5"),
            "배송 중": ("#1d4ed8", "#dbeafe"), "입고 완료": ("#6b7280", "#f3f4f6")}.get(s, ("#6b7280", "#f3f4f6"))

def status_badge(s):
    fg, bg = status_color(s)
    return f'<span class="of-badge" style="background:{bg};color:{fg};">{s}</span>'


# ════════════════════════════════════════════
# 사이드바
# ════════════════════════════════════════════
with st.sidebar:
    st.markdown("#### 📦 OrderFlow")
    st.caption("AI 발주 관리")
    st.markdown("---")
    page = st.radio("메뉴", ["📊 대시보드", "⬆️ 발주서 업로드", "📋 발주 목록", "🔧 관리"], label_visibility="collapsed")
    st.markdown("---")
    if API_KEY:
        st.markdown('<small style="color:#047857;">● AI 연결됨</small>', unsafe_allow_html=True)
    else:
        st.markdown('<small style="color:#e53e3e;">● API 미설정</small>', unsafe_allow_html=True)


# ════════════════════════════════════════════
# 📊 대시보드
# ════════════════════════════════════════════
if page == "📊 대시보드":
    st.markdown('<div class="of-title">대시보드</div>', unsafe_allow_html=True)
    st.markdown('<div class="of-subtitle">발주 현황을 한눈에 확인하세요</div>', unsafe_allow_html=True)

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

        # ── 입고 캘린더 ──
        st.markdown("#### 📅 입고 캘린더")

        now = datetime.now()
        cal_col1, cal_col2 = st.columns([3, 1])
        with cal_col2:
            month_offset = st.selectbox("월 선택", [0, 1, 2], format_func=lambda x: (now + timedelta(days=30*x)).strftime("%Y년 %m월"), label_visibility="collapsed")

        target_date = now + timedelta(days=30 * month_offset)
        year, month = target_date.year, target_date.month
        first_weekday, num_days = monthrange(year, month)

        # 해당 월의 입고 예정 수집
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
                except:
                    pass

        weekdays = ["월", "화", "수", "목", "금", "토", "일"]
        cal_html = '<div class="cal-grid">'
        for w in weekdays:
            cal_html += f'<div class="cal-header">{w}</div>'

        # 빈 칸
        for _ in range(first_weekday):
            cal_html += '<div class="cal-day empty"></div>'

        for day in range(1, num_days + 1):
            classes = "cal-day"
            dot = ""
            tooltip = ""

            if day == now.day and month == now.month and year == now.year:
                classes += " today"

            if day in eta_map:
                day_orders = eta_map[day]
                is_past = datetime(year, month, day) < datetime(now.year, now.month, now.day)
                classes += " has-order"
                if is_past:
                    classes += " urgent"
                total_items = sum(sum(it.get("quantity", 0) for it in o.get("items", [])) for o in day_orders)
                dot = f'<div class="cal-dot"></div>'
                tooltip = f'{len(day_orders)}건 · {total_items:,}개'

            cal_html += f'<div class="{classes}" title="{tooltip}">{day}{dot}</div>'

        cal_html += '</div>'

        with cal_col1:
            st.markdown(cal_html, unsafe_allow_html=True)

        # 캘린더 아래 입고 예정 리스트
        if eta_map:
            st.markdown("")
            sorted_days = sorted(eta_map.keys())
            for day in sorted_days:
                day_date = f"{year}-{month:02d}-{day:02d}"
                is_past = day_date < today_str
                for o in eta_map[day]:
                    items = o.get("items", [])
                    total_qty = sum(i.get("quantity", 0) for i in items)
                    item_names = ", ".join(i.get("display_name") or i.get("name", "") for i in items[:3])
                    if len(items) > 3:
                        item_names += f" 외 {len(items)-3}종"
                    status = o.get("status", "확인 대기")
                    fg, bg = status_color(status)

                    card_class = "of-card of-urgent" if is_past else "of-card"
                    late_badge = ""
                    if is_past:
                        days_late = (datetime.now() - datetime.strptime(day_date, "%Y-%m-%d")).days
                        late_badge = f'<span style="background:#e53e3e;color:white;padding:3px 10px;border-radius:10px;font-size:11px;font-weight:600;margin-left:8px;">{days_late}일 지연</span>'

                    st.markdown(f"""
                    <div class="{card_class}">
                        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
                            <div>
                                <span style="font-size:13px;color:#86868b;">{month}/{day}</span>
                                <span style="font-weight:600;color:#1d1d1f;margin-left:8px;">{o.get('supplier','')}</span>
                                {late_badge}
                            </div>
                            <div style="display:flex;gap:10px;align-items:center;">
                                <span style="font-size:14px;font-weight:600;color:#1d1d1f;">{fmt_amount(o.get('total_amount'), o.get('currency'))}</span>
                                {status_badge(status)}
                            </div>
                        </div>
                        <div style="font-size:13px;color:#6e6e73;margin-top:8px;">📦 {total_qty:,}개 — {item_names}</div>
                    </div>""", unsafe_allow_html=True)

        st.markdown("---")

        # ── 전체 발주 카드 ──
        st.markdown("#### 전체 발주")

        status_filter = st.selectbox("필터", ["전체", "확인 대기", "확인 완료", "배송 중", "입고 완료"], label_visibility="collapsed")
        filtered = orders if status_filter == "전체" else [o for o in orders if o.get("status") == status_filter]

        for o in filtered[:20]:
            items = o.get("items", [])
            total_qty = sum(i.get("quantity", 0) for i in items)
            status = o.get("status", "확인 대기")

            st.markdown(f"""
            <div class="of-card">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;">
                    <div>
                        <div style="font-size:11px;color:#86868b;margin-bottom:2px;">{o['id']}</div>
                        <div style="font-size:16px;font-weight:600;color:#1d1d1f;">{o.get('supplier','')}</div>
                    </div>
                    <div style="text-align:right;">
                        <div style="font-size:18px;font-weight:700;color:#1d1d1f;">{fmt_amount(o.get('total_amount'), o.get('currency'))}</div>
                        {status_badge(status)}
                    </div>
                </div>
                <div style="display:flex;gap:20px;flex-wrap:wrap;font-size:12px;color:#86868b;margin-top:12px;">
                    <span>발주 {o.get('order_date','-')}</span>
                    <span>입고 {o.get('eta') or '-'}</span>
                    <span>{total_qty:,}개 · {len(items)}종</span>
                </div>
                <div style="margin-top:12px;padding-top:12px;border-top:1px solid #f5f5f7;">
                    <table style="width:100%;font-size:12px;border-collapse:collapse;">
                        <tr style="color:#86868b;"><td style="padding:4px 0;width:45%;">품목</td><td style="width:10%;">내부명</td><td style="width:15%;text-align:right;">수량</td><td style="width:15%;text-align:right;">단가</td><td style="width:15%;text-align:right;">소계</td></tr>
                        {''.join(f"""<tr style="color:#1d1d1f;">
                            <td style="padding:4px 0;font-size:12px;">{it.get('name','')}</td>
                            <td style="padding:4px 0;font-size:11px;color:#0071e3;">{it.get('display_name','') if it.get('display_name') and it.get('display_name') != it.get('name') else ''}</td>
                            <td style="text-align:right;">{it.get('quantity',0):,}</td>
                            <td style="text-align:right;">{it.get('unit_price',0):,}</td>
                            <td style="text-align:right;font-weight:500;">{it.get('subtotal',0):,}</td>
                        </tr>
                        {f'<tr><td colspan="5" style="padding:2px 0;font-size:11px;color:#86868b;">💬 {it["memo"]}</td></tr>' if it.get('memo') else ''}
                        """ for it in items[:8])}
                        {'<tr><td colspan="5" style="padding:4px 0;font-size:11px;color:#86868b;">… 외 '+str(len(items)-8)+'개 품목</td></tr>' if len(items) > 8 else ''}
                    </table>
                </div>
                {f'<div style="margin-top:8px;font-size:12px;color:#0071e3;background:#f5f5f7;padding:8px 12px;border-radius:8px;">📝 {o.get("notes")}</div>' if o.get("notes") else ''}
            </div>""", unsafe_allow_html=True)


# ════════════════════════════════════════════
# ⬆️ 발주서 업로드
# ════════════════════════════════════════════
elif page == "⬆️ 발주서 업로드":
    st.markdown('<div class="of-title">발주서 업로드</div>', unsafe_allow_html=True)
    st.markdown('<div class="of-subtitle">파일을 업로드하면 AI가 자동으로 분석합니다</div>', unsafe_allow_html=True)

    if not API_KEY:
        st.error("Claude API 키가 설정되지 않았습니다. 관리자에게 문의하세요.")
        st.stop()

    uploaded = st.file_uploader(
        "발주서 파일 선택",
        type=["xlsx", "xls", "csv", "pdf", "jpg", "jpeg", "png", "webp"],
        help="Excel, PDF, 이미지 파일 지원",
    )

    if uploaded:
        # 미리보기
        st.markdown("#### 업로드된 파일")
        st.caption(f"{uploaded.name} · {uploaded.size/1024:.1f} KB")

        ext = uploaded.name.split(".")[-1].lower()
        if ext in ("jpg", "jpeg", "png", "webp"):
            st.image(uploaded, width=400)
            uploaded.seek(0)
        elif ext in ("xlsx", "xls", "csv"):
            try:
                preview = pd.read_csv(uploaded) if ext == "csv" else pd.read_excel(uploaded)
                st.dataframe(preview.head(10), use_container_width=True, hide_index=True)
                uploaded.seek(0)
            except:
                uploaded.seek(0)

        st.markdown("---")

        # AI 분석
        st.markdown("#### AI 분석 결과")

        cache_key = f"parsed_{uploaded.name}_{uploaded.size}"

        if cache_key not in st.session_state:
            st.info("⏳ AI가 발주서를 분석하고 있습니다...")
            try:
                uploaded.seek(0)
                result = parse_file(uploaded, API_KEY)
                st.session_state[cache_key] = result
                st.rerun()
            except Exception as e:
                st.error(f"분석 오류: {e}")
                st.session_state[cache_key] = None

        parsed = st.session_state.get(cache_key)

        if parsed:
            st.success("분석 완료! 내용을 확인하고 수정하세요.")

            # 기본 정보
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                parsed["supplier"] = st.text_input("거래처", value=parsed.get("supplier", ""))
            with col2:
                parsed["order_date"] = st.text_input("발주일", value=parsed.get("order_date", ""))
            with col3:
                parsed["eta"] = st.text_input("입고예정일", value=parsed.get("eta") or "")
            with col4:
                parsed["currency"] = st.selectbox(
                    "통화", ["KRW", "CNY", "USD", "JPY"],
                    index=["KRW", "CNY", "USD", "JPY"].index(parsed.get("currency", "KRW"))
                    if parsed.get("currency") in ["KRW", "CNY", "USD", "JPY"] else 0,
                )

            st.markdown("---")

            # ── 품목별 수정 (내부명 + 메모) ──
            st.markdown("#### 품목 상세")
            st.caption("원본명은 발주서 그대로, 내부명은 우리 회사에서 부르는 이름, 메모는 특이사항을 적으세요.")

            items = parsed.get("items", [])
            updated_items = []

            for idx, item in enumerate(items):
                with st.container():
                    st.markdown(f'<div class="of-card">', unsafe_allow_html=True)

                    c1, c2 = st.columns(2)
                    with c1:
                        original_name = st.text_input(
                            "원본 제품명",
                            value=item.get("name", ""),
                            key=f"name_{idx}",
                            disabled=True,
                        )
                    with c2:
                        display_name = st.text_input(
                            "내부 제품명 (수정 가능)",
                            value=item.get("display_name") or item.get("name", ""),
                            key=f"display_{idx}",
                            help="팀원들이 알아볼 수 있는 이름으로 수정하세요",
                        )

                    c3, c4, c5 = st.columns(3)
                    with c3:
                        qty = st.number_input("수량", value=int(item.get("quantity", 0)), key=f"qty_{idx}", min_value=0)
                    with c4:
                        price = st.number_input("단가", value=float(item.get("unit_price", 0)), key=f"price_{idx}", min_value=0.0, format="%.2f")
                    with c5:
                        subtotal = st.number_input("소계", value=float(item.get("subtotal", 0)), key=f"sub_{idx}", min_value=0.0, format="%.2f")

                    memo = st.text_input(
                        "💬 메모",
                        value=item.get("memo", ""),
                        key=f"memo_{idx}",
                        placeholder="예: 색온도 확인 필요, 포장 변경됨 등",
                    )

                    st.markdown('</div>', unsafe_allow_html=True)

                    updated_items.append({
                        "name": original_name,
                        "display_name": display_name if display_name != original_name else "",
                        "quantity": qty,
                        "unit_price": price,
                        "subtotal": subtotal,
                        "memo": memo,
                    })

            parsed["items"] = updated_items
            parsed["total_amount"] = sum(i.get("subtotal", 0) for i in updated_items)

            total_qty = sum(i.get("quantity", 0) for i in updated_items)

            st.markdown("---")
            st.markdown(f"**합계:** {total_qty:,}개 · {fmt_amount(parsed.get('total_amount'), parsed.get('currency'))}")

            # 발주 전체 메모
            order_notes = st.text_area(
                "📝 발주 메모",
                value=parsed.get("notes") or "",
                placeholder="이 발주 건에 대한 전체 메모를 남기세요...",
                height=80,
            )
            parsed["notes"] = order_notes if order_notes else None

            st.markdown("---")

            col_s1, col_s2 = st.columns(2)
            with col_s1:
                if st.button("발주 등록", type="primary", use_container_width=True):
                    order = {
                        "supplier": parsed["supplier"],
                        "order_date": parsed.get("order_date"),
                        "eta": parsed.get("eta") or None,
                        "currency": parsed.get("currency", "KRW"),
                        "items": parsed.get("items", []),
                        "total_amount": parsed.get("total_amount", 0),
                        "status": "확인 대기",
                        "source_file": uploaded.name,
                        "notes": parsed.get("notes"),
                    }
                    order_id = save_order(order)
                    st.balloons()
                    st.success(f"등록 완료! 발주번호: **{order_id}**")
                    del st.session_state[cache_key]

            with col_s2:
                if st.button("다시 분석", use_container_width=True):
                    del st.session_state[cache_key]
                    st.rerun()

        elif cache_key in st.session_state and st.session_state[cache_key] is None:
            if st.button("다시 시도"):
                del st.session_state[cache_key]
                st.rerun()


# ════════════════════════════════════════════
# 📋 발주 목록
# ════════════════════════════════════════════
elif page == "📋 발주 목록":
    st.markdown('<div class="of-title">발주 목록</div>', unsafe_allow_html=True)
    st.markdown('<div class="of-subtitle">발주 내역을 확인하고 관리하세요</div>', unsafe_allow_html=True)

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

        with st.expander(f"{oid} — {o.get('supplier', '')} · {fmt_amount(o.get('total_amount'), o.get('currency'))} · {status}"):

            c1, c2 = st.columns([3, 1])
            with c1:
                st.markdown(f"""
                <div style="display:flex;gap:24px;flex-wrap:wrap;font-size:13px;color:#6e6e73;margin-bottom:12px;">
                    <span>📅 {o.get('order_date','-')}</span>
                    <span>🚚 {o.get('eta') or '-'}</span>
                    <span>📦 {total_qty:,}개 · {len(items)}종</span>
                    <span>📎 {o.get('source_file','-')}</span>
                </div>""", unsafe_allow_html=True)

            with c2:
                new_status = st.selectbox(
                    "상태", ["확인 대기", "확인 완료", "배송 중", "입고 완료"],
                    index=["확인 대기", "확인 완료", "배송 중", "입고 완료"].index(status)
                    if status in ["확인 대기", "확인 완료", "배송 중", "입고 완료"] else 0,
                    key=f"st_{oid}", label_visibility="collapsed",
                )
                if new_status != status:
                    if st.button("저장", key=f"save_{oid}", use_container_width=True):
                        update_order_status(oid, new_status)
                        st.rerun()

            # 품목 테이블 (수정 가능)
            if items:
                st.markdown("**품목 상세** (내부명과 메모를 수정할 수 있습니다)")

                items_data = []
                for it in items:
                    items_data.append({
                        "원본명": it.get("name", ""),
                        "내부명": it.get("display_name") or "",
                        "수량": it.get("quantity", 0),
                        "단가": it.get("unit_price", 0),
                        "소계": it.get("subtotal", 0),
                        "메모": it.get("memo", ""),
                    })

                edited = st.data_editor(
                    pd.DataFrame(items_data),
                    use_container_width=True,
                    hide_index=True,
                    disabled=["원본명", "수량", "단가", "소계"],
                    column_config={
                        "원본명": st.column_config.TextColumn("원본명", width="medium"),
                        "내부명": st.column_config.TextColumn("내부명", width="medium", help="팀원들이 알아볼 수 있는 이름"),
                        "수량": st.column_config.NumberColumn("수량", format="%.0f"),
                        "단가": st.column_config.NumberColumn("단가", format="%.2f"),
                        "소계": st.column_config.NumberColumn("소계", format="%.2f"),
                        "메모": st.column_config.TextColumn("메모", width="medium", help="품목별 특이사항"),
                    },
                    key=f"edit_{oid}",
                )

                if st.button("품목 정보 저장", key=f"items_save_{oid}"):
                    new_items = []
                    for i, row in edited.iterrows():
                        original = items[i] if i < len(items) else {}
                        new_items.append({
                            "name": row["원본명"],
                            "display_name": row["내부명"] if row["내부명"] else "",
                            "quantity": original.get("quantity", row["수량"]),
                            "unit_price": original.get("unit_price", row["단가"]),
                            "subtotal": original.get("subtotal", row["소계"]),
                            "memo": row["메모"] if row["메모"] else "",
                        })
                    o_copy = dict(o)
                    o_copy["items"] = new_items
                    update_order(oid, o_copy)
                    st.success("저장 완료!")
                    st.rerun()

            if o.get("notes"):
                st.info(f"📝 {o['notes']}")

            if st.button("삭제", key=f"del_{oid}"):
                delete_order(oid)
                st.rerun()

    # 엑셀 다운로드
    st.markdown("---")
    if orders:
        summary_data = []
        items_data = []
        for o in orders:
            summary_data.append({
                "발주번호": o["id"], "거래처": o.get("supplier"), "발주일": o.get("order_date"),
                "입고예정일": o.get("eta"), "통화": o.get("currency"), "총금액": o.get("total_amount"),
                "상태": o.get("status"), "출처": o.get("source_file"),
            })
            for i in o.get("items", []):
                items_data.append({
                    "발주번호": o["id"],
                    "원본명": i.get("name"),
                    "내부명": i.get("display_name") or "",
                    "수량": i.get("quantity"),
                    "단가": i.get("unit_price"),
                    "소계": i.get("subtotal"),
                    "메모": i.get("memo", ""),
                })

        buf = BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            pd.DataFrame(summary_data).to_excel(writer, sheet_name="발주요약", index=False)
            if items_data:
                pd.DataFrame(items_data).to_excel(writer, sheet_name="품목상세", index=False)

        st.download_button(
            "엑셀 다운로드",
            data=buf.getvalue(),
            file_name=f"발주현황_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


# ════════════════════════════════════════════
# 🔧 관리
# ════════════════════════════════════════════
elif page == "🔧 관리":
    st.markdown('<div class="of-title">관리</div>', unsafe_allow_html=True)

    st.markdown("#### API 상태")
    if API_KEY:
        st.success(f"API 키 설정됨 (···{API_KEY[-6:]})")
        st.caption("Streamlit Cloud Secrets에서 관리됩니다.")
    else:
        st.error("API 키 미설정")

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
            if p.exists(): p.unlink()
            st.session_state["confirm_delete"] = False
            st.rerun()
        else:
            st.session_state["confirm_delete"] = True
            st.warning("한 번 더 누르면 삭제됩니다.")
