"""
발주서 파싱 모듈 - Claude API를 사용하여 발주서를 자동 분석합니다.
"""

import json
import re
import base64
import io
import anthropic
import pandas as pd


MAX_CONTENT_LENGTH = 15000  # Claude에 보낼 최대 텍스트 길이


PARSE_PROMPT = """당신은 발주서/주문서 파싱 전문가입니다.
업로드된 파일의 내용을 분석하여 아래 JSON 형식으로 정확하게 추출해주세요.

반드시 아래 JSON 형식만 출력하세요. 다른 텍스트는 절대 포함하지 마세요.

{
  "supplier": "거래처/공급업체명",
  "order_date": "YYYY-MM-DD (발주일/주문일)",
  "eta": "YYYY-MM-DD (입고예정일, 없으면 null)",
  "currency": "KRW, CNY, USD 등",
  "items": [
    {"name": "품목명", "color": "색상/칼라 (없으면 null)", "quantity": 숫자, "unit_price": 숫자, "subtotal": 숫자}
  ],
  "total_amount": 총금액(숫자),
  "notes": "특이사항 (없으면 null)"
}

규칙:
- 숫자 필드는 숫자만 (쉼표, 통화기호 제외)
- 날짜는 YYYY-MM-DD
- 못 찾은 정보는 null
- 중국어/한국어/영어 모두 처리
- 색상/칼라/颜色/color 정보가 있으면 반드시 color 필드에 포함
- 같은 품목이라도 색상이 다르면 별도 항목으로 분리
- JSON만 출력하고, 설명이나 마크다운은 절대 붙이지 마세요"""


def parse_file(uploaded_file, api_key: str) -> dict:
    """업로드된 파일을 Claude API로 파싱합니다."""
    file_bytes = uploaded_file.read()
    file_name = uploaded_file.name.lower()

    if file_name.endswith((".xlsx", ".xls")):
        content = _read_excel(file_bytes)
        return _call_claude(content, "text", api_key)

    elif file_name.endswith(".csv"):
        content = pd.read_csv(io.BytesIO(file_bytes)).to_string(index=False)
        return _call_claude(_truncate(content), "text", api_key)

    elif file_name.endswith(".pdf"):
        content = _read_pdf(file_bytes)
        if content and content.strip():
            return _call_claude(_truncate(content), "text", api_key)
        return _call_claude(file_bytes, "image", api_key, "application/pdf")

    elif file_name.endswith((".jpg", ".jpeg", ".png", ".webp")):
        media_type = _guess_media_type(file_bytes)
        return _call_claude(file_bytes, "image", api_key, media_type)

    else:
        raise ValueError(f"지원하지 않는 파일 형식: {uploaded_file.name}")


def _read_excel(file_bytes: bytes) -> str:
    """엑셀 파일을 읽고, 발주서에 필요한 핵심 열만 추출합니다."""
    sheets = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None)
    parts = []

    for name, df in sheets.items():
        # NaN으로만 구성된 행/열 제거
        df = df.dropna(how="all").dropna(axis=1, how="all")

        # 핵심 열 키워드로 필터링 (열이 많을 때)
        if df.shape[1] > 12:
            key_words = [
                "품명", "품목", "제품", "型号", "name", "item", "product",
                "색", "칼라", "color", "颜色",
                "수량", "数量", "qty", "quantity",
                "단가", "单价", "price", "unit",
                "금액", "총금액", "总额", "total", "amount", "subtotal",
                "납기", "예상", "교기", "交期", "eta", "delivery", "date",
                "주문", "발주", "下单", "order",
                "NO", "no", "번호",
                "한국", "韩文", "내부",
                "거래", "공급", "supplier",
            ]
            keep_cols = []
            for col in df.columns:
                col_str = str(col).lower()
                if any(kw.lower() in col_str for kw in key_words):
                    keep_cols.append(col)
            if keep_cols:
                df = df[keep_cols]

        text = df.to_string(index=False)
        parts.append(f"[시트: {name}] ({df.shape[0]}행 x {df.shape[1]}열)")
        parts.append(text)

    combined = "\n\n".join(parts)
    return _truncate(combined)


def _truncate(text: str) -> str:
    """텍스트가 너무 길면 앞부분만 잘라서 반환합니다."""
    if len(text) <= MAX_CONTENT_LENGTH:
        return text
    return text[:MAX_CONTENT_LENGTH] + f"\n\n... (전체 {len(text)}자 중 {MAX_CONTENT_LENGTH}자까지 표시)"


def _read_pdf(file_bytes: bytes) -> str | None:
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        parts = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                parts.append(f"[페이지 {i+1}]\n{text}")
        return "\n\n".join(parts) if parts else None
    except Exception:
        return None


def _call_claude(content, content_type: str, api_key: str, media_type: str = "image/png") -> dict:
    client = anthropic.Anthropic(api_key=api_key)

    if content_type == "image":
        b64 = base64.standard_b64encode(content).decode("utf-8") if isinstance(content, bytes) else content
        messages_content = [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
            {"type": "text", "text": PARSE_PROMPT},
        ]
    else:
        messages_content = [
            {"type": "text", "text": f"아래는 발주서 파일 내용입니다:\n\n---\n{content}\n---\n\n{PARSE_PROMPT}"}
        ]

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8000,
        messages=[{"role": "user", "content": messages_content}],
    )

    raw = response.content[0].text.strip()

    # JSON 추출 (여러 패턴 시도)
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()

    # JSON 객체 부분만 추출 (앞뒤 텍스트 제거)
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start >= 0 and end > start:
        raw = raw[start:end]

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 제어 문자 제거 후 재시도
        cleaned = re.sub(r'[\x00-\x1f\x7f]', ' ', raw)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # 잘린 JSON 복구: 마지막 완전한 항목까지 잘라내기
            # 마지막 완전한 }를 찾아서 그 뒤를 정리
            last_complete = cleaned.rfind("},")
            if last_complete > 0:
                partial = cleaned[:last_complete + 1]
                open_b = partial.count("[") - partial.count("]")
                open_c = partial.count("{") - partial.count("}")
                partial += "]" * max(open_b, 0)
                partial += "}" * max(open_c, 0)
                try:
                    return json.loads(partial)
                except json.JSONDecodeError:
                    pass
            raise ValueError("AI 응답을 파싱할 수 없습니다. 파일을 다시 업로드해주세요.")


def _guess_media_type(data: bytes) -> str:
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return "image/png"
    if data[:2] == b'\xff\xd8':
        return "image/jpeg"
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return "image/webp"
    return "image/png"
