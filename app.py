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
                # 품목 테이블
                rows = []
                for it in items:
                    display = it.get("display_name") or ""
                    name = it.get("name", "")
                    show_name = display if display else name
                    color = it.get("color") or ""
                    if color:
                        show_name = f"{show_name} ({color})"
                    memo = it.get("memo", "")
                    rows.append({
                        "품목": show_name,
                        "수량": it.get("quantity", 0),
                        "단가": it.get("unit_price", 0),
                        "소계": it.get("subtotal", 0),
                        "메모": memo,
                    })
                df = pd.DataFrame(rows)
                st.dataframe(df, use_container_width=True, hide_index=True)

                if o.get("notes"):
                    st.info(f"📝 {o['notes']}")


# ════════════════════════════════════════════
# ⬆️ 발주서 업로드
# ════════════════════════════════════════════
elif page == "⬆️ 발주서 업로드":
    st.title("발주서 업로드")
    st.caption("파일을 업로드하면 AI가 자동으로 분석합니다")

    if not API_KEY:
        st.error("Claude API 키가 설정되지 않았습니다. 관리자에게 문의하세요.")
        st.stop()

    uploaded = st.file_uploader(
        "발주서 파일 선택",
        type=["xlsx", "xls", "csv", "pdf", "jpg", "jpeg", "png", "webp"],
        help="Excel, PDF, 이미지 파일 지원",
    )

    if uploaded:
        st.markdown("#### 업로드된 파일")
        st.caption(f"{uploaded.name} · {uploaded.size / 1024:.1f} KB")

        ext = uploaded.name.split(".")[-1].lower()
        if ext in ("jpg", "jpeg", "png", "webp"):
            st.image(uploaded, width=400)
            uploaded.seek(0)
        elif ext in ("xlsx", "xls", "csv"):
            try:
                preview = pd.read_csv(uploaded) if ext == "csv" else pd.read_excel(uploaded)
                st.dataframe(preview.head(10), use_container_width=True, hide_index=True)
                uploaded.seek(0)
            except Exception:
                uploaded.seek(0)

        st.markdown("---")
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
                od = parse_date(parsed.get("order_date"))
                selected_od = st.date_input("발주일", value=od or datetime.now().date())
                parsed["order_date"] = selected_od.strftime("%Y-%m-%d")
            with col3:
                eta = parse_date(parsed.get("eta"))
                selected_eta = st.date_input("입고예정일", value=eta or None)
                parsed["eta"] = selected_eta.strftime("%Y-%m-%d") if selected_eta else None
            with col4:
                currencies = ["KRW", "CNY", "USD", "JPY"]
                cur_val = parsed.get("currency", "KRW")
                cur_idx = currencies.index(cur_val) if cur_val in currencies else 0
                parsed["currency"] = st.selectbox("통화", currencies, index=cur_idx)

            st.markdown("---")

            # ── 품목별 수정 ──
            st.markdown("#### 품목 상세")
            st.caption("내부명: 우리 팀에서 부르는 이름으로 수정  ·  메모: 특이사항 기록")

            items = parsed.get("items", [])
            updated_items = []

            for idx, item in enumerate(items):
                color_label = f" ({item.get('color')})" if item.get("color") else ""
                with st.expander(f"#{idx + 1}  {item.get('name', '')}{color_label}", expanded=True):
                    c1, c2, c_color = st.columns([2, 2, 1])
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
                    with c_color:
                        color = st.text_input(
                            "색상",
                            value=item.get("color") or "",
                            key=f"color_{idx}",
                            placeholder="예: 흑색, 3000K",
                        )

                    c3, c4, c5 = st.columns(3)
                    with c3:
                        qty = st.number_input(
                            "수량", value=int(item.get("quantity", 0)),
                            key=f"qty_{idx}", min_value=0,
                        )
                    with c4:
                        price = st.number_input(
                            "단가", value=float(item.get("unit_price", 0)),
                            key=f"price_{idx}", min_value=0.0, format="%.2f",
                        )
                    with c5:
                        subtotal = st.number_input(
                            "소계", value=float(item.get("subtotal", 0)),
                            key=f"sub_{idx}", min_value=0.0, format="%.2f",
                        )

                    memo = st.text_input(
                        "메모",
                        value=item.get("memo", ""),
                        key=f"memo_{idx}",
                        placeholder="예: 색온도 확인 필요, 포장 변경됨 등",
                    )

                    updated_items.append({
                        "name": original_name,
                        "display_name": display_name if display_name != original_name else "",
                        "color": color,
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

            # ── 품목 테이블 (전체 수정 가능) ──
            if items:
                st.markdown("**품목 상세**")

                items_data = []
                for it in items:
                    items_data.append({
                        "원본명": it.get("name", ""),
                        "색상": it.get("color") or "",
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
                    column_config={
                        "원본명": st.column_config.TextColumn("원본명", width="medium"),
                        "색상": st.column_config.TextColumn("색상", width="small"),
                        "내부명": st.column_config.TextColumn("내부명", width="medium", help="팀원들이 알아볼 수 있는 이름"),
                        "수량": st.column_config.NumberColumn("수량", format="%.0f"),
                        "단가": st.column_config.NumberColumn("단가", format="%.2f"),
                        "소계": st.column_config.NumberColumn("소계", format="%.2f"),
                        "메모": st.column_config.TextColumn("메모", width="medium"),
                    },
                    key=f"edit_{oid}",
                )

            st.markdown("---")

            # ── 저장 / 삭제 버튼 ──
            save_col, del_col = st.columns([3, 1])
            with save_col:
                if st.button("💾 저장", key=f"save_all_{oid}", type="primary", use_container_width=True):
                    # 품목 데이터 수집
                    new_items = []
                    if items:
                        for i, row in edited.iterrows():
                            new_items.append({
                                "name": row["원본명"],
                                "color": row["색상"] if row["색상"] else "",
                                "display_name": row["내부명"] if row["내부명"] else "",
                                "quantity": row["수량"],
                                "unit_price": row["단가"],
                                "subtotal": row["소계"],
                                "memo": row["메모"] if row["메모"] else "",
                            })
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
            for i in o.get("items", []):
                all_items_data.append({
                    "발주번호": o["id"],
                    "원본명": i.get("name"),
                    "색상": i.get("color") or "",
                    "내부명": i.get("display_name") or "",
                    "수량": i.get("quantity"),
                    "단가": i.get("unit_price"),
                    "소계": i.get("subtotal"),
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
