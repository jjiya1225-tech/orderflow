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

    stats = get_stats()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("전체 발주", f"{stats['total']}건")
    c2.metric("확인 대기", f"{stats['pending']}건")
    c3.metric("배송 중", f"{stats['shipping']}건")
    c4.metric("거래처", f"{stats['suppliers']}곳")

    st.divider()
    st.markdown("### 최근 발주 현황")

    orders = load_all_orders()
    if not orders:
        st.info("📭 등록된 발주가 없습니다. **⬆️ 발주서 업로드** 메뉴에서 시작하세요!")
    else:
        status_filter = st.selectbox("상태 필터", ["전체", "확인 대기", "확인 완료", "배송 중", "입고 완료"], label_visibility="collapsed")
        filtered = orders if status_filter == "전체" else [o for o in orders if o.get("status") == status_filter]

        rows = []
        for o in filtered[:30]:
            items = o.get("items", [])
            summary = ", ".join(i["name"] for i in items[:2])
            if len(items) > 2:
                summary += f" 외 {len(items)-2}종"
            total_qty = sum(i.get("quantity", 0) for i in items)
            rows.append({
                "발주번호": o["id"],
                "거래처": o.get("supplier", "-"),
                "품목": summary or "-",
                "총수량": total_qty,
                "금액": fmt_amount(o.get("total_amount"), o.get("currency")),
                "입고예정일": o.get("eta") or "-",
                "상태": o.get("status", "-"),
            })

        if rows:
            st.dataframe(
                pd.DataFrame(rows),
                use_container_width=True,
                hide_index=True,
                column_config={"총수량": st.column_config.NumberColumn(format="%d개")},
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
        col_left, col_right = st.columns(2)

        # 왼쪽: 파일 미리보기
        with col_left:
            st.markdown("#### 📎 업로드된 파일")
            st.markdown(f"**{uploaded.name}** ({uploaded.size/1024:.1f} KB)")

            ext = uploaded.name.split(".")[-1].lower()
            if ext in ("jpg", "jpeg", "png", "webp"):
                st.image(uploaded, use_container_width=True)
                uploaded.seek(0)
            elif ext in ("xlsx", "xls", "csv"):
                try:
                    preview = pd.read_csv(uploaded) if ext == "csv" else pd.read_excel(uploaded)
                    st.dataframe(preview.head(10), use_container_width=True, hide_index=True)
                    uploaded.seek(0)
                except:
                    pass

        # 오른쪽: AI 분석 결과
        with col_right:
            st.markdown("#### 🤖 AI 분석 결과")

            cache_key = f"parsed_{uploaded.name}_{uploaded.size}"

            if cache_key not in st.session_state:
                with st.spinner("AI가 발주서를 분석하고 있습니다..."):
                    try:
                        result = parse_file(uploaded, API_KEY)
                        st.session_state[cache_key] = result
                    except Exception as e:
                        st.error(f"분석 오류: {e}")
                        st.session_state[cache_key] = None

            parsed = st.session_state.get(cache_key)

            if parsed:
                st.success("✅ AI 분석 완료!")
                st.divider()

                # 수정 가능한 필드
                parsed["supplier"] = st.text_input("거래처", value=parsed.get("supplier", ""))
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    parsed["order_date"] = st.text_input("발주일", value=parsed.get("order_date", ""))
                with col_d2:
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
