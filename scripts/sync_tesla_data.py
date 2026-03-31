#!/usr/bin/env python3
"""
Tesla 충전소 데이터 자동 동기화 스크립트
매주 수요일 03:00 KST (화요일 18:00 UTC) 자동 실행

동작:
1. Tesla 공식 리스트 페이지 fetch (SC / DC)
2. __NEXT_DATA__ JSON 파싱 (SSR 페이지 → 브라우저 불필요)
3. 현재 index.html 데이터와 비교
4. 신규/변경/삭제 감지 → index.html 자동 업데이트
"""

import os
import re
import sys
import json
import time
from datetime import datetime

try:
    import requests
except ImportError:
    print("requests 라이브러리가 없습니다. pip install requests 실행 후 재시도하세요.")
    sys.exit(1)

# ── 설정 ─────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

SC_LIST_URL = "https://www.tesla.com/ko_KR/findus/list/superchargers/South+Korea"
DC_LIST_URL = "https://www.tesla.com/ko_KR/findus/list/chargers/South+Korea"
DETAIL_BASE  = "https://www.tesla.com/ko_KR/findus/location"
INDEX_HTML   = os.path.join(os.path.dirname(__file__), "..", "index.html")

REGION_MAP = {
    "서울특별시": "서울", "서울": "서울",
    "경기도": "경기", "경기": "경기",
    "인천광역시": "인천", "인천": "인천",
    "부산광역시": "부산", "부산": "부산",
    "대구광역시": "대구", "대구": "대구",
    "대전광역시": "대전", "대전": "대전",
    "광주광역시": "광주", "광주": "광주",
    "울산광역시": "울산", "울산": "울산",
    "세종특별자치시": "세종", "세종": "세종",
    "강원도": "강원", "강원특별자치도": "강원", "강원": "강원",
    "충청북도": "충북", "충북": "충북",
    "충청남도": "충남", "충남": "충남",
    "경상북도": "경북", "경북": "경북",
    "경상남도": "경남", "경남": "경남",
    "전라북도": "전북", "전북특별자치도": "전북", "전북": "전북",
    "전라남도": "전남", "전남": "전남",
    "제주특별자치도": "제주", "제주": "제주",
}


# ── 유틸 ─────────────────────────────────────────────────────
def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def fetch_html(url, retries=3):
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code == 200:
                return resp.text
            log(f"HTTP {resp.status_code}: {url}")
        except Exception as e:
            log(f"Fetch 오류 (시도 {attempt+1}/{retries}): {e}")
        if attempt < retries - 1:
            time.sleep(2 ** attempt)
    return None


def extract_next_data(html):
    """<script id="__NEXT_DATA__"> 에서 JSON 추출"""
    m = re.search(
        r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html, re.DOTALL
    )
    if m:
        return json.loads(m.group(1))
    return None


def normalize_region(city, state_province=""):
    for src in [city, state_province]:
        for k, v in REGION_MAP.items():
            if src and src.startswith(k):
                return v
    return "기타"


def parse_list_data(raw_items, charger_type):
    """Tesla 리스트 → {slug: info_dict}"""
    result = {}
    for item in raw_items:
        slug = item.get("location_url_slug", "")
        if not slug:
            continue
        src = item.get("_source", {})
        name = src.get("marketing", {}).get("display_name", "")

        # 주소 (한국어 우선)
        addr_list = src.get("key_data", {}).get("address_by_locale", [])
        addr_kr = next((a for a in addr_list if a.get("locale") == "ko-KR"), None)
        addr_en = next((a for a in addr_list if a.get("locale") == "en-US"), {})
        fallback = addr_list[0] if addr_list else {}

        if addr_kr:
            nav = addr_kr.get("nav_street_name", "")
            a1  = addr_kr.get("address_2", "")
            a2  = addr_kr.get("address_1", "")
            address = nav or f"{a1} {a2}".strip()
            city    = addr_kr.get("city", "")
            state   = addr_kr.get("state_province", "")
        else:
            address = (f"{addr_en.get('address_1','')} {addr_en.get('address_2','')}").strip()
            city    = addr_en.get("city", fallback.get("city", ""))
            state   = addr_en.get("state_province", fallback.get("state_province", ""))

        region = normalize_region(city, state)

        # 전화번호
        if charger_type == "charger":
            phone = src.get("destination_charger_function", {}).get("phone_number", "") or ""
            status = src.get("destination_charger_function", {}).get("project_status", "Open")
            url_key = "chargerUrl"
        else:
            raw_phone = src.get("marketing", {}).get("roadside_assistance_number", "") or ""
            phone = re.sub(r"\s+", "-", raw_phone.strip())
            status = src.get("supercharger_function", {}).get("project_status", "Open")
            url_key = "teslaUrl"

        result[slug] = {
            "slug": slug,
            "name": name,
            "region": region,
            "address": address,
            "lat": float(item.get("latitude", 0) or 0),
            "lng": float(item.get("longitude", 0) or 0),
            "phone": phone,
            "status": status,
            url_key: f"https://www.tesla.com/ko_KR/findus/location/{charger_type}/{slug}",
        }
    return result


def fetch_detail(slug, charger_type):
    """상세 페이지에서 stalls/kW/가격 추출"""
    url = f"{DETAIL_BASE}/{charger_type}/{slug}"
    html = fetch_html(url)
    if not html:
        return {}

    # __NEXT_DATA__ 우선
    nd = extract_next_data(html)
    if nd:
        try:
            fd = nd["props"]["pageProps"]["formattedData"]
            stalls = fd.get("chargerQuantity")
            kw     = fd.get("chargerMaxPower")
            pricing = fd.get("chargerPricing", []) or []
            tesla_price = other_price = None
            for p in pricing:
                for d in p.get("pricingDetails", []):
                    m = re.search(r"₩(\d+)", d.get("rate", ""))
                    if m:
                        price = int(m.group(1))
                        label = p.get("chargingLabel", "")
                        if "Tesla" in label or "오너" in label:
                            tesla_price = price
                        else:
                            other_price = price
            return {
                "stalls": stalls,
                "maxKw": kw,
                "teslaPrice": tesla_price,
                "otherPrice": other_price,
            }
        except Exception as e:
            log(f"  상세 파싱 오류 ({slug}): {e}")

    # fallback: regex
    stalls = None
    kw     = None
    m1 = re.search(r'"chargerQuantity"\s*:\s*(\d+)', html)
    m2 = re.search(r'"chargerMaxPower"\s*:\s*(\d+)', html)
    if m1: stalls = int(m1.group(1))
    if m2: kw     = int(m2.group(1))
    return {"stalls": stalls, "maxKw": kw}


def js_val(v):
    """Python → JS 리터럴"""
    if v is None:          return "null"
    if isinstance(v, bool): return "true" if v else "false"
    if isinstance(v, (int, float)):
        # 좌표 같은 경우 소수점 유지
        if isinstance(v, float) and v != int(v):
            return repr(v)
        return str(int(v)) if v == int(v) else repr(v)
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def make_sc_line(e):
    return (
        f"  {{ name: {js_val(e['name'])}, region: {js_val(e['region'])}, "
        f"address: {js_val(e.get('address',''))}, "
        f"note: {js_val(e.get('note',''))}, "
        f"lat: {js_val(e.get('lat',0))}, lng: {js_val(e.get('lng',0))}, "
        f"phone: {js_val(e.get('phone',''))}, "
        f"teslaUrl: {js_val(e.get('teslaUrl',''))}, "
        f"stalls: {js_val(e.get('stalls'))}, maxKw: {js_val(e.get('maxKw'))}, "
        f"teslaPrice: {js_val(e.get('teslaPrice'))}, otherPrice: {js_val(e.get('otherPrice'))} }}"
    )


def make_dc_line(e):
    return (
        f"  {{ name: {js_val(e['name'])}, region: {js_val(e['region'])}, "
        f"address: {js_val(e.get('address',''))}, "
        f"detail: {js_val(e.get('detail',''))}, "
        f"phone: {js_val(e.get('phone',''))}, "
        f"lat: {js_val(e.get('lat',0))}, lng: {js_val(e.get('lng',0))}, "
        f"chargerUrl: {js_val(e.get('chargerUrl',''))}, "
        f"stalls: {js_val(e.get('stalls'))}, maxKw: {js_val(e.get('maxKw'))} }}"
    )


def get_current_slugs(html, pattern):
    """index.html에서 현재 slug 목록 추출"""
    return set(re.findall(pattern, html))


def append_to_js_array(html, array_name, new_lines):
    """JS 배열 끝(];) 직전에 새 항목 추가"""
    # array_name 이후 처음 나오는 ]; 를 찾아서 앞에 추가
    marker = f"const {array_name} = ["
    idx = html.find(marker)
    if idx == -1:
        return html
    # 해당 배열의 닫는 ]; 찾기
    depth = 0
    pos = html.index("[", idx)
    start = pos
    while pos < len(html):
        if html[pos] in "[{":
            depth += 1
        elif html[pos] in "]}":
            depth -= 1
            if depth == 0:
                break
        pos += 1
    # pos는 ] 위치
    insert = ",\n" + ",\n".join(new_lines)
    return html[:pos] + insert + html[pos:]


def set_github_output(key, value):
    out_file = os.environ.get("GITHUB_OUTPUT", "")
    if out_file:
        with open(out_file, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")


# ── 메인 ─────────────────────────────────────────────────────
def main():
    log("=== Tesla 충전소 데이터 동기화 시작 ===")

    # 1. Tesla 리스트 페이지 fetch
    log("슈퍼차저 목록 fetch 중...")
    sc_html = fetch_html(SC_LIST_URL)
    time.sleep(1)
    log("데스티네이션 목록 fetch 중...")
    dc_html = fetch_html(DC_LIST_URL)

    if not sc_html or not dc_html:
        log("❌ Tesla 페이지 fetch 실패. 종료.")
        set_github_output("has_changes", "false")
        set_github_output("error", "fetch_failed")
        sys.exit(0)  # 에러여도 workflow 성공으로 종료 (다음 주 재시도)

    # 2. __NEXT_DATA__ 파싱
    sc_nd = extract_next_data(sc_html)
    dc_nd = extract_next_data(dc_html)

    if not sc_nd or not dc_nd:
        log("❌ __NEXT_DATA__ 파싱 실패 (페이지 구조 변경됐을 수 있음)")
        set_github_output("has_changes", "false")
        set_github_output("error", "parse_failed")
        sys.exit(0)

    sc_raw = sc_nd["props"]["pageProps"]["data"]
    dc_raw = dc_nd["props"]["pageProps"]["data"]
    log(f"Tesla 데이터: SC {len(sc_raw)}개, DC {len(dc_raw)}개")

    # 3. 정규화
    tesla_sc = parse_list_data(sc_raw, "supercharger")
    tesla_dc = parse_list_data(dc_raw, "charger")

    # 4. 현재 index.html 읽기
    html_path = os.path.abspath(INDEX_HTML)
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    current_sc_slugs = get_current_slugs(html, r'teslaUrl:\s*["\']https://www\.tesla\.com/[^/]+/findus/location/supercharger/([^"\']+)["\']')
    current_dc_slugs = get_current_slugs(html, r'chargerUrl:\s*["\']https://www\.tesla\.com/[^/]+/findus/location/charger/([^"\']+)["\']')
    log(f"현재 index.html: SC {len(current_sc_slugs)}개, DC {len(current_dc_slugs)}개")

    # 5. 변경사항 감지
    new_sc_slugs     = set(tesla_sc.keys()) - current_sc_slugs
    new_dc_slugs     = set(tesla_dc.keys()) - current_dc_slugs
    removed_sc_slugs = current_sc_slugs - set(tesla_sc.keys())
    removed_dc_slugs = current_dc_slugs - set(tesla_dc.keys())

    changes = []
    if new_sc_slugs:
        changes.append(f"신규 슈퍼차저 {len(new_sc_slugs)}개: {', '.join(sorted(new_sc_slugs))}")
    if new_dc_slugs:
        changes.append(f"신규 데스티네이션 {len(new_dc_slugs)}개: {', '.join(sorted(new_dc_slugs))}")
    if removed_sc_slugs:
        changes.append(f"⚠️ Tesla 목록 제거 SC {len(removed_sc_slugs)}개: {', '.join(sorted(removed_sc_slugs))}")
    if removed_dc_slugs:
        changes.append(f"⚠️ Tesla 목록 제거 DC {len(removed_dc_slugs)}개: {', '.join(sorted(removed_dc_slugs))}")

    # 이름 변경 감지 (SC)
    for slug, item in tesla_sc.items():
        if slug not in current_sc_slugs:
            continue
        m = re.search(
            rf'name:\s*"([^"]+)"[^}}]+teslaUrl:\s*"[^"]*supercharger/{re.escape(slug)}"',
            html
        )
        if m and m.group(1) != item["name"]:
            changes.append(f"SC 이름변경: '{m.group(1)}' → '{item['name']}' ({slug})")

    if not changes:
        log("✅ 변경사항 없음.")
        set_github_output("has_changes", "false")
        return

    log(f"\n변경사항 {len(changes)}건 감지:")
    for c in changes:
        log(f"  · {c}")

    # 6. 신규 항목 상세 정보 fetch
    new_sc_entries = []
    for slug in sorted(new_sc_slugs):
        log(f"  신규 SC 상세 fetch: {slug}")
        detail = fetch_detail(slug, "supercharger")
        entry  = tesla_sc[slug].copy()
        entry.update(detail)
        entry.setdefault("note", "")
        new_sc_entries.append(entry)
        time.sleep(1.5)

    new_dc_entries = []
    for slug in sorted(new_dc_slugs):
        log(f"  신규 DC 상세 fetch: {slug}")
        detail = fetch_detail(slug, "charger")
        entry  = tesla_dc[slug].copy()
        entry.update(detail)
        entry.setdefault("detail", "")
        new_dc_entries.append(entry)
        time.sleep(1.5)

    # 7. index.html 업데이트
    new_html = html

    if new_sc_entries:
        lines = [make_sc_line(e) for e in new_sc_entries]
        new_html = append_to_js_array(new_html, "superchargers", lines)
        log(f"  슈퍼차저 {len(new_sc_entries)}개 추가됨")

    if new_dc_entries:
        lines = [make_dc_line(e) for e in new_dc_entries]
        new_html = append_to_js_array(new_html, "stations", lines)
        log(f"  데스티네이션 {len(new_dc_entries)}개 추가됨")

    # 총 개수 업데이트 (tabAllCnt, tabDestCnt, tabScCnt)
    total_sc = len(current_sc_slugs) + len(new_sc_slugs)
    total_dc = len(current_dc_slugs) + len(new_dc_slugs)
    total_all = total_sc + total_dc

    new_html = re.sub(r'(id="tabAllCnt">)\d+', rf'\g<1>{total_all}', new_html)
    new_html = re.sub(r'(id="tabDestCnt">)\d+', rf'\g<1>{total_dc}', new_html)
    new_html = re.sub(r'(id="tabScCnt">)\d+', rf'\g<1>{total_sc}', new_html)
    # OG description 업데이트
    new_html = re.sub(
        r'(전국 )\d+(개 Tesla 충전소)',
        rf'\g<1>{total_all}\g<2>',
        new_html
    )

    if new_html != html:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(new_html)
        log("✅ index.html 저장 완료")

    # 8. GitHub Actions output
    summary = " | ".join(changes)
    set_github_output("has_changes", "true")
    set_github_output("changes_summary", summary[:500])  # 500자 제한

    log(f"\n=== 동기화 완료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")


if __name__ == "__main__":
    main()
