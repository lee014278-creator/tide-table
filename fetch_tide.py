"""
KHOA(국립해양조사원) 조위관측소 실측·예측 조위 API를 호출해서
울진(후포)/삼척(묵호) 지역의 오늘~내일 만조·간조 시각을 계산하고
tide-data.json 파일로 저장하는 스크립트.

GitHub Actions에서 매일 자동 실행됩니다.
API 키는 환경변수 KHOA_API_KEY 로 전달받습니다 (GitHub Secrets에서 주입).
"""

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

API_BASE = "https://apis.data.go.kr/1192136/surveyTideLevel/GetSurveyTideLevelApiService"

# 지역명: (관측소코드, 관측소 실제명)
STATIONS = {
    "uljin": {"obs_code": "DT_0011", "obs_name": "후포", "label": "울진 (후포 기준)"},
    "samcheok": {"obs_code": "DT_0006", "obs_name": "묵호", "label": "삼척 (묵호 기준)"},
    "yeongdeok": {"obs_code": "DT_0091", "obs_name": "포항", "label": "영덕 (포항 기준)"},
}


def fetch_day(api_key: str, obs_code: str, date_str: str):
    """특정 관측소, 특정 날짜의 10분 간격 예측조위 데이터를 가져온다."""
    params = {
        "serviceKey": api_key,
        "type": "json",
        "obsCode": obs_code,
        "reqDate": date_str,
        "min": "10",
        "pageNo": "1",
        "numOfRows": "150",  # 24시간 / 10분 = 144개 + 여유
    }
    url = API_BASE + "?" + urllib.parse.urlencode(params)

    with urllib.request.urlopen(url, timeout=20) as resp:
        raw = resp.read().decode("utf-8")

    data = json.loads(raw)

    # 실제 응답이 {"response": {...}} 형태이거나, {"header":..., "body":...}처럼
    # 감싸는 껍데기 없이 바로 오는 경우가 둘 다 있어서 둘 다 처리한다.
    payload = data.get("response", data)

    header = payload.get("header")
    if not header or header.get("resultCode") != "00":
        err_msg = (header or {}).get("resultMsg") or str(data)[:200]
        raise RuntimeError(f"API 오류 [{obs_code} {date_str}]: {err_msg}")

    body = payload.get("body", {})
    items = body.get("items")
    # items가 없거나 빈 문자열일 수 있음 (데이터 없음)
    if not items or "item" not in items:
        return []

    item_list = items["item"]
    if isinstance(item_list, dict):  # 결과가 1건이면 dict로 옴
        item_list = [item_list]

    points = []
    for it in item_list:
        try:
            t = datetime.strptime(it["obsrvnDt"], "%Y-%m-%d %H:%M")
            h = float(it["tdlvHgt"])  # 예측조위(cm)
            points.append((t, h))
        except (KeyError, ValueError, TypeError):
            continue

    points.sort(key=lambda p: p[0])
    return points


DAYS_AHEAD = 30  # 오늘 포함 앞으로 며칠치를 가져올지


def build_region_data(api_key: str, obs_code: str, base_date: datetime):
    """오늘부터 DAYS_AHEAD일치 데이터를 합쳐서 만조/간조 리스트를 만든다."""
    points = []
    for offset in range(DAYS_AHEAD):
        day_str = (base_date + timedelta(days=offset)).strftime("%Y%m%d")
        points += fetch_day(api_key, obs_code, day_str)
    points.sort(key=lambda p: p[0])

    extrema_with_date = []
    for i in range(1, len(points) - 1):
        prev_h = points[i - 1][1]
        cur_t, cur_h = points[i]
        next_h = points[i + 1][1]
        kind = None
        if cur_h >= prev_h and cur_h >= next_h and cur_h > prev_h:
            kind = "만조"
        elif cur_h <= prev_h and cur_h <= next_h and cur_h < prev_h:
            kind = "간조"
        if kind:
            extrema_with_date.append({
                "type": kind,
                "date": cur_t.strftime("%Y-%m-%d"),
                "time": cur_t.strftime("%H:%M"),
                "height_cm": round(cur_h, 1),
            })

    return extrema_with_date


def main():
    api_key = os.environ.get("KHOA_API_KEY")
    if not api_key:
        raise SystemExit("환경변수 KHOA_API_KEY가 설정되지 않았습니다.")

    now_kst = datetime.utcnow() + timedelta(hours=9)  # KST 보정
    today = datetime(now_kst.year, now_kst.month, now_kst.day)

    result = {
        "updated_at": now_kst.strftime("%Y-%m-%d %H:%M KST"),
        "regions": {},
    }

    for region_key, info in STATIONS.items():
        try:
            events = build_region_data(api_key, info["obs_code"], today)
        except Exception as e:
            events = []
            print(f"[경고] {region_key} 데이터 수집 실패: {e}")

        result["regions"][region_key] = {
            "label": info["label"],
            "obs_name": info["obs_name"],
            "events": events,
        }

    with open("tide-data.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("tide-data.json 저장 완료")


if __name__ == "__main__":
    main()
