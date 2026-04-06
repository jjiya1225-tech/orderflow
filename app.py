"""
OrderFlow - AI 발주 관리 시스템
팀원들은 URL만 열면 바로 사용 가능합니다.
"""

import streamlit as st
import pandas as pd
from datetime import datetime
from io import BytesIO

from parser import parse_file
from storage import (
    save_order, load_all_orders, load_order, update_order_status,
    delete_order, get_stats, export_all_json, import_orders,
)

# ─── 페이지 설정 ───
st.set_page_config(page_title="OrderFlow", page_icon="📦", layout="wide", initial_sidebar_state="expanded")

# ─── API 키 (서버 secrets에서 가져옴 → 팀원들은 입력 불필요) ───
API_KEY = st.secrets.get("ANTHROPIC_API_KEY", "")

# ─── 스타일 ───
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Noto Sans KR', sans-serif; }
.block-container { padding-top: 1.5rem; }
[data-testid="stMetric"] {
    background: white; border: 1px solid #e5e7eb; border-radius: 12px;
    padding: 16px 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}
[data-testid="stMetricLabel"] { font-size: 13px; }
[data-testid="stMetricValue"] { font-size: 26px; font-weight: 700; }
div[data-testid="stExpander"] { border: 1px solid #e5e7eb; border-radius: 10px; }
.status-badge { display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 500; }
.st-pending { background: #fffbeb; color: #d97706; }
.st-confirmed { background: #f0fdf4; color: #16a34a; }
.st-shipping { background: #eff6ff; color: #2563eb; }
.st-arrived { background: #f3f4f6; color: #4b5563; }
</style>
""", unsafe_allow_html=True)


def status_html(s):
    cls = {"확인 대기": "st-pending", "확인 완료": "st-confirmed", "배송 중": "st-shipping", "입고 완료": "st-arrived"}.get(s, "st-pending")
    return f'<span class="status-badge {cls}">{s}</span>'


def fmt_amount(amt, cur="KRW"):
    if not amt: return "-"
    sym = {"KRW": "₩", "CNY": "¥", "USD": "$", "JPY": "¥"}.get(cur, "")
    return f"{sym}{amt:,.0f}"


# ─── 사이드바 ───
with st.sidebar:
    st.markdown("### 📦 OrderFlow")
    st.caption("AI 발주 관리 시스템")
    st.divider()

    page = st.radio("메뉴", ["📊 대시보드", "⬆️ 발주서 업로드", "📋 발주 목록", "🔧 관리"], label_visibility="collapsed")

    st.divider()
    if API_KEY:
        st.success("✅ AI 파싱 사용 가능")
    else:
        st.error("⚠️ API 키 미설정")
    st.caption(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}")


# ════════════════════════════════════════════
# 📊 대시보드
# ════════════════════════════════════════════
if page == "📊 대시보드":
    st.markdown("## 📊 대시보드")

    orders = load_all_orders()
    stats = get_stats()

    # ── 통계 카드 ──
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("전체 발주", f"{stats['total']}건")
    c2.metric("확인 대기", f"{stats['pending']}건")
    c3.metric("배송 중", f"{stats['shipping']}건")
    c4.metric("거래처", f"{stats['suppliers']}곳")

    if not orders:
        st.divider()
        st.info("📭 등록된 발주가 없습니다. **⬆️ 발주서 업로드** 메뉴에서 시작하세요!")

    else:
        st.divider()

        # ── 입고 예정 타임라인 ──
        today_str = datetime.now().strftime("%Y-%m-%d")
        upcoming = [o for o in orders if o.get("eta") and o["eta"] >= today_str and o.get("status") != "입고 완료"]
        upcoming.sort(key=lambda x: x.get("eta", ""))

        overdue = [o for o in orders if o.get("eta") and o["eta"] < today_str and o.get("status") not in ("입고 완료",)]

        if overdue:
            st.markdown("### 🚨 입고 지연")
            for o in overdue:
                items = o.get("items", [])
                total_qty = sum(i.get("quantity", 0) for i in items)
                days_late = (datetime.now() - datetime.strptime(o["eta"], "%Y-%m-%d")).days
                st.markdown(
                    f"""<div style="background:#fef2f2;border:1px solid #fecaca;border-radius:10px;padding:14px 18px;margin-bottom:10px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
                        <div>
                            <span style="font-weight:700;color:#dc2626;">{o['id']}</span>
                            <span style="color:#6b7280;margin-left:8px;">{o.get('supplier','')}</span>
                        </div>
                        <div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap;">
                            <span style="font-size:13px;">📦 {total_qty:,}개</span>
                            <span style="font-size:13px;font-weight:600;">{fmt_amount(o.get('total_amount'), o.get('currency'))}</span>
                            <span style="background:#dc2626;color:white;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:500;">{days_late}일 지연</span>
                        </div>
                    </div>
                    <div style="font-size:12px;color:#9ca3af;margin-top:6px;">예정일: {o['eta']} | {', '.join(i['name'] for i in items[:3])}{' 외 '+str(len(items)-3)+'종' if len(items)>3 else ''}</div>
                    </div>""",
                    unsafe_allow_html=True,
                )

        if upcoming:
            st.markdown("### 📅 입고 예정")
            for o in upcoming[:5]:
                items = o.get("items", [])
                total_qty = sum(i.get("quantity", 0) for i in items)
                days_left = (datetime.strptime(o["eta"], "%Y-%m-%d") - datetime.now()).days + 1
                status = o.get("status", "확인 대기")

                if days_left <= 3:
                    border_color = "#f59e0b"
                    bg_color = "#fffbeb"
                    urgency = f"D-{days_left}"
                elif days_left <= 7:
                    border_color = "#3b82f6"
                    bg_color = "#eff6ff"
                    urgency = f"D-{days_left}"
                else:
                    border_color = "#e5e7eb"
                    bg_color = "#ffffff"
                    urgency = f"D-{days_left}"

                status_colors = {"확인 대기": "#d97706", "확인 완료": "#16a34a", "배송 중": "#2563eb"}
                s_color = status_colors.get(status, "#6b7280")

                st.markdown(
                    f"""<div style="background:{bg_color};border:1px solid {border_color};border-left:4px solid {border_color};border-radius:10px;padding:14px 18px;margin-bottom:10px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
                        <div>
                            <span style="font-weight:700;color:#111827;">{o['id']}</span>
                            <span style="color:#6b7280;margin-left:8px;">{o.get('supplier','')}</span>
                        </div>
                        <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;">
                            <span style="font-size:13px;">📦 {total_qty:,}개</span>
                            <span style="font-size:13px;font-weight:600;">{fmt_amount(o.get('total_amount'), o.get('currency'))}</span>
                            <span style="background:{s_color};color:white;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:500;">{status}</span>
                            <span style="font-weight:700;font-size:14px;color:{border_color};">{urgency}</span>
                        </div>
                    </div>
                    <div style="font-size:12px;color:#9ca3af;margin-top:6px;">입고예정: {o['eta']} | {', '.join(i['name'] for i in items[:3])}{' 외 '+str(len(items)-3)+'종' if len(items)>3 else ''}</div>
                    </div>""",
                    unsafe_allow_html=True,
                )
        else:
            if not overdue:
                st.info("📅 예정된 입고 건이 없습니다.")

        st.divider()

        # ── 상태별 현황 ──
        st.markdown("### 📋 상태별 현황")

        status_counts = {}
        for o in orders:
            s = o.get("status", "확인 대기")
            status_counts[s] = status_counts.get(s, 0) + 1

        status_order = ["확인 대기", "확인 완료", "배송 중", "입고 완료"]
        status_emoji = {"확인 대기": "🟡", "확인 완료": "🟢", "배송 중": "🔵", "입고 완료": "⚪"}
        status_bg = {"확인 대기": "#fffbeb", "확인 완료": "#f0fdf4", "배송 중": "#eff6ff", "입고 완료": "#f9fafb"}
        status_border = {"확인 대기": "#fde68a", "확인 완료": "#bbf7d0", "배송 중": "#bfdbfe", "입고 완료": "#e5e7eb"}

        cols = st.columns(4)
        for i, s in enumerate(status_order):
            count = status_counts.get(s, 0)
            s_orders = [o for o in orders if o.get("status") == s]
            total_amt = sum(o.get("total_amount", 0) for o in s_orders)
            total_qty = sum(sum(it.get("quantity", 0) for it in o.get("items", [])) for o in s_orders)

            with cols[i]:
                st.markdown(
                    f"""<div style="background:{status_bg[s]};border:1px solid {status_border[s]};border-radius:10px;padding:16px;text-align:center;">
                    <div style="font-size:24px;margin-bottom:4px;">{status_emoji[s]}</div>
                    <div style="font-size:13px;color:#6b7280;margin-bottom:2px;">{s}</div>
                    <div style="font-size:28px;font-weight:700;color:#111827;">{count}건</div>
                    <div style="font-size:11px;color:#9ca3af;margin-top:6px;">{total_qty:,}개 | {total_amt:,.0f}</div>
                    </div>""",
                    unsafe_allow_html=True,
                )

        st.divider()

        # ── 최근 발주 카드 ──
        st.markdown("### 🗂️ 전체 발주 요약")

        status_filter = st.selectbox("상태 필터", ["전체", "확인 대기", "확인 완료", "배송 중", "입고 완료"], label_visibility="collapsed")
        filtered = orders if status_filter == "전체" else [o for o in orders if o.get("status") == status_filter]

        for o in filtered[:20]:
            items = o.get("items", [])
            total_qty = sum(i.get("quantity", 0) for i in items)
            status = o.get("status", "확인 대기")
            s_color = {"확인 대기": "#d97706", "확인 완료": "#16a34a", "배송 중": "#2563eb", "입고 완료": "#6b7280"}.get(status, "#6b7280")
            s_bg = {"확인 대기": "#fffbeb", "확인 완료": "#f0fdf4", "배송 중": "#eff6ff", "입고 완료": "#f9fafb"}.get(status, "#f9fafb")

            st.markdown(
                f"""<div style="background:white;border:1px solid #e5e7eb;border-radius:12px;padding:18px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,0.04);">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;">
                    <div>
                        <div style="font-size:15px;font-weight:700;color:#111827;margin-bottom:4px;">{o['id']}</div>
                        <div style="font-size:14px;color:#374151;">{o.get('supplier','')}</div>
                    </div>
                    <div style="text-align:right;">
                        <div style="font-size:18px;font-weight:700;color:#2563eb;">{fmt_amount(o.get('total_amount'), o.get('currency'))}</div>
                        <span style="background:{s_bg};color:{s_color};padding:3px 12px;border-radius:12px;font-size:12px;font-weight:500;display:inline-block;margin-top:4px;">{status}</span>
                    </div>
                </div>
                <div style="margin-top:12px;display:flex;gap:24px;flex-wrap:wrap;font-size:13px;color:#6b7280;">
                    <span>📅 발주일: {o.get('order_date','-')}</span>
                    <span>🚚 입고예정: {o.get('eta') or '-'}</span>
                    <span>📦 {total_qty:,}개 ({len(items)}종)</span>
                    <span>📎 {o.get('source_file','-')}</span>
                </div>
                <div style="margin-top:10px;padding-top:10px;border-top:1px solid #f3f4f6;">
                    <table style="width:100%;font-size:12px;border-collapse:collapse;">
                        <tr style="color:#9ca3af;"><td style="padding:3px 0;width:50%;">품목명</td><td style="width:16%;text-align:right;">수량</td><td style="width:16%;text-align:right;">단가</td><td style="width:18%;text-align:right;">소계</td></tr>
                        {''.join(f'<tr style="color:#374151;"><td style="padding:3px 0;">{it.get("name","")}</td><td style="text-align:right;">{it.get("quantity",0):,}</td><td style="text-align:right;">{it.get("unit_price",0):,}</td><td style="text-align:right;font-weight:500;">{it.get("subtotal",0):,}</td></tr>' for it in items[:6])}
                        {'<tr style="color:#9ca3af;"><td colspan="4" style="padding:3px 0;">... 외 '+str(len(items)-6)+'개 품목</td></tr>' if len(items) > 6 else ''}
                    </table>
                </div>
                {f'<div style="margin-top:8px;font-size:12px;color:#2563eb;background:#eff6ff;padding:6px 10px;border-radius:6px;">📝 {o.get("notes")}</div>' if o.get("notes") else ''}
                </div>""",
                unsafe_allow_html=True,
            )


# ════════════════════════════════════════════
# ⬆️ 발주서 업로드
# ════════════════════════════════════════════
elif page == "⬆️ 발주서 업로드":
    st.markdown("## ⬆️ 발주서 업로드")
    st.caption("발주서 파일을 업로드하면 AI가 자동으로 분석합니다")

    if not API_KEY:
        st.error("⚠️ Claude API 키가 설정되지 않았습니다. 관리자에게 문의하세요.")
        st.stop()

    # 파일 업로드
    uploaded = st.file_uploader(
        "발주서 파일 선택",
        type=["xlsx", "xls", "csv", "pdf", "jpg", "jpeg", "png", "webp"],
        help="Excel, PDF, 이미지 파일 지원 (최대 20MB)",
    )

    if uploaded:
        # 파일 미리보기
        st.markdown("#### 📎 업로드된 파일")
        st.markdown(f"**{uploaded.name}** ({uploaded.size/1024:.1f} KB)")

        ext = uploaded.name.split(".")[-1].lower()
        if ext in ("jpg", "jpeg", "png", "webp"):
            st.image(uploaded, width=400)
            uploaded.seek(0)
        elif ext in ("xlsx", "xls", "csv"):
            try:
                preview = pd.read_csv(uploaded) if ext == "csv" else pd.read_excel(uploaded)
                st.dataframe(preview.head(10), use_container_width=True, hide_index=True)
                uploaded.seek(0)
            except Exception as preview_err:
                st.warning(f"미리보기 실패: {preview_err}")
                uploaded.seek(0)

        st.divider()

        # AI 분석
        st.markdown("#### 🤖 AI 분석 결과")

        cache_key = f"parsed_{uploaded.name}_{uploaded.size}"

        if cache_key not in st.session_state:
            st.info("⏳ AI가 발주서를 분석하고 있습니다... (최대 30초 소요)")
            try:
                uploaded.seek(0)
                result = parse_file(uploaded, API_KEY)
                st.session_state[cache_key] = result
                st.rerun()
            except Exception as e:
                st.error(f"❌ AI 분석 오류: {e}")
                st.markdown(f"```\n{type(e).__name__}: {e}\n```")
                st.markdown("**확인 사항:**")
                st.markdown("- Streamlit Cloud Secrets에 `ANTHROPIC_API_KEY`가 올바르게 입력되어 있는지 확인하세요")
                st.markdown("- API 키가 `sk-ant-`로 시작하는지 확인하세요")
                st.markdown("- [Anthropic Console](https://console.anthropic.com)에서 크레딧이 남아있는지 확인하세요")
                st.session_state[cache_key] = None

        parsed = st.session_state.get(cache_key)

        if parsed:
            st.success("✅ AI 분석 완료! 아래 내용을 확인하고 수정할 수 있습니다.")
            st.divider()

            # 수정 가능한 필드
            col_f1, col_f2, col_f3 = st.columns(3)
            with col_f1:
                parsed["supplier"] = st.text_input("거래처", value=parsed.get("supplier", ""))
            with col_f2:
                parsed["order_date"] = st.text_input("발주일", value=parsed.get("order_date", ""))
            with col_f3:
                parsed["eta"] = st.text_input("입고예정일", value=parsed.get("eta") or "")

            parsed["currency"] = st.selectbox(
                "통화",
                ["KRW", "CNY", "USD", "JPY"],
                index=["KRW", "CNY", "USD", "JPY"].index(parsed.get("currency", "KRW"))
                if parsed.get("currency") in ["KRW", "CNY", "USD", "JPY"] else 0,
            )

            # 품목 테이블 (수정 가능)
            if parsed.get("items"):
                st.markdown("**품목 목록:**")
                items_df = pd.DataFrame(parsed["items"])
                edited = st.data_editor(
                    items_df,
                    use_container_width=True,
                    hide_index=True,
                    num_rows="dynamic",
                    column_config={
                        "name": st.column_config.TextColumn("품목명"),
                        "quantity": st.column_config.NumberColumn("수량", format="%.0f"),
                        "unit_price": st.column_config.NumberColumn("단가", format="%.0f"),
                        "subtotal": st.column_config.NumberColumn("소계", format="%.0f"),
                    },
                )
                parsed["items"] = edited.to_dict("records")
                parsed["total_amount"] = sum(i.get("subtotal", 0) for i in parsed["items"])

            total_qty = sum(i.get("quantity", 0) for i in parsed.get("items", []))
            st.markdown(f"**총수량:** {total_qty:,.0f}개 | **총금액:** {fmt_amount(parsed.get('total_amount'), parsed.get('currency'))}")

            if parsed.get("notes"):
                st.info(f"📝 비고: {parsed['notes']}")

            # 등록 버튼
            st.divider()
            col_s1, col_s2 = st.columns(2)
            with col_s1:
                if st.button("✅ 발주 등록", type="primary", use_container_width=True):
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
                    st.success(f"🎉 등록 완료! 발주번호: **{order_id}**")
                    del st.session_state[cache_key]

            with col_s2:
                if st.button("🔄 다시 분석", use_container_width=True):
                    del st.session_state[cache_key]
                    st.rerun()

        elif cache_key in st.session_state and st.session_state[cache_key] is None:
            if st.button("🔄 다시 시도", use_container_width=True):
                del st.session_state[cache_key]
                st.rerun()


# ════════════════════════════════════════════
# 📋 발주 목록
# ════════════════════════════════════════════
elif page == "📋 발주 목록":
    st.markdown("## 📋 발주 목록")

    orders = load_all_orders()
    if not orders:
        st.info("📭 등록된 발주가 없습니다.")
        st.stop()

    # 검색 + 필터
    col_s, col_f = st.columns([2, 1])
    with col_s:
        search = st.text_input("🔍 검색", placeholder="발주번호, 거래처...", label_visibility="collapsed")
    with col_f:
        sfilter = st.selectbox("상태", ["전체", "확인 대기", "확인 완료", "배송 중", "입고 완료"])

    filtered = orders
    if search:
        q = search.lower()
        filtered = [o for o in filtered if q in (o["id"] + o.get("supplier", "")).lower()]
    if sfilter != "전체":
        filtered = [o for o in filtered if o.get("status") == sfilter]

    st.caption(f"총 **{len(filtered)}**건")

    for o in filtered:
        oid = o["id"]
        status = o.get("status", "확인 대기")
        emoji = {"확인 대기": "🟡", "확인 완료": "🟢", "배송 중": "🔵", "입고 완료": "⚪"}.get(status, "⚪")
        items = o.get("items", [])
        summary = ", ".join(i["name"] for i in items[:2])
        if len(items) > 2:
            summary += f" 외 {len(items)-2}종"

        with st.expander(f"{emoji} **{oid}** — {o.get('supplier', '')} | {summary} | {status}"):
            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown(f"**발주일:** {o.get('order_date', '-')}")
                st.markdown(f"**입고예정일:** {o.get('eta') or '-'}")
            with c2:
                st.markdown(f"**품목수:** {len(items)}개")
                st.markdown(f"**총수량:** {sum(i.get('quantity',0) for i in items):,.0f}개")
            with c3:
                st.markdown(f"**총금액:** {fmt_amount(o.get('total_amount'), o.get('currency'))}")
                st.markdown(f"**출처:** {o.get('source_file', '-')}")

            if items:
                st.dataframe(
                    pd.DataFrame(items),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "name": "품목명",
                        "quantity": st.column_config.NumberColumn("수량", format="%.0f"),
                        "unit_price": st.column_config.NumberColumn("단가", format="%.0f"),
                        "subtotal": st.column_config.NumberColumn("소계", format="%.0f"),
                    },
                )

            if o.get("notes"):
                st.info(f"📝 {o['notes']}")

            # 상태 변경 + 삭제
            col_a, col_b, col_c = st.columns([2, 1, 1])
            with col_a:
                new_status = st.selectbox(
                    "상태 변경",
                    ["확인 대기", "확인 완료", "배송 중", "입고 완료"],
                    index=["확인 대기", "확인 완료", "배송 중", "입고 완료"].index(status)
                    if status in ["확인 대기", "확인 완료", "배송 중", "입고 완료"] else 0,
                    key=f"st_{oid}",
                    label_visibility="collapsed",
                )
            with col_b:
                if new_status != status:
                    if st.button("💾 저장", key=f"save_{oid}"):
                        update_order_status(oid, new_status)
                        st.success("✅ 변경 완료!")
                        st.rerun()
            with col_c:
                if st.button("🗑️ 삭제", key=f"del_{oid}"):
                    delete_order(oid)
                    st.rerun()

    # 엑셀 다운로드
    st.divider()
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
                items_data.append({"발주번호": o["id"], **i})

        buf = BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            pd.DataFrame(summary_data).to_excel(writer, sheet_name="발주요약", index=False)
            if items_data:
                pd.DataFrame(items_data).to_excel(writer, sheet_name="품목상세", index=False)

        st.download_button(
            "📥 전체 발주 엑셀 다운로드",
            data=buf.getvalue(),
            file_name=f"발주현황_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


# ════════════════════════════════════════════
# 🔧 관리
# ════════════════════════════════════════════
elif page == "🔧 관리":
    st.markdown("## 🔧 관리")

    # API 상태
    st.markdown("### 🔑 Claude API 상태")
    if API_KEY:
        st.success(f"✅ API 키가 설정되어 있습니다 (···{API_KEY[-6:]})")
        st.caption("API 키는 Streamlit Cloud Secrets에서 관리됩니다. 변경이 필요하면 관리자에게 문의하세요.")
    else:
        st.error("⚠️ API 키가 설정되지 않았습니다")
        st.markdown("""
        **관리자 설정 방법:**
        1. [Streamlit Cloud](https://share.streamlit.io) 대시보드 접속
        2. 이 앱의 Settings → Secrets 메뉴
        3. 아래 내용을 입력:
        ```toml
        ANTHROPIC_API_KEY = "sk-ant-your-key-here"
        ```
        """)

    st.divider()

    # 데이터 백업 / 복원
    st.markdown("### 💾 데이터 백업 & 복원")
    st.caption("정기적으로 JSON 백업을 받아두면 안전합니다.")

    col1, col2 = st.columns(2)
    with col1:
        json_data = export_all_json()
        st.download_button(
            "📥 JSON 백업 다운로드",
            data=json_data,
            file_name=f"orderflow_backup_{datetime.now().strftime('%Y%m%d')}.json",
            mime="application/json",
            use_container_width=True,
        )
    with col2:
        backup_file = st.file_uploader("JSON 백업 복원", type=["json"], label_visibility="collapsed")
        if backup_file:
            import json
            try:
                data = json.loads(backup_file.read())
                added = import_orders(data.get("orders", []))
                st.success(f"✅ {added}건 복원 완료 (중복 제외)")
            except Exception as e:
                st.error(f"복원 오류: {e}")

    st.divider()
    st.markdown("### ⚠️ 데이터 초기화")
    if st.button("🗑️ 전체 데이터 삭제", type="secondary"):
        if st.session_state.get("confirm_delete"):
            from pathlib import Path
            p = Path("data/orders.json")
            if p.exists():
                p.unlink()
            st.session_state["confirm_delete"] = False
            st.success("삭제 완료")
            st.rerun()
        else:
            st.session_state["confirm_delete"] = True
            st.warning("정말 삭제하시겠습니까? 한 번 더 버튼을 누르면 삭제됩니다.")
