#!/usr/bin/env python3
"""
產生 data/segment_cameras.json — 路段 → 鄰近即時影像攝影機的對照表。

資料來源：
  1. twipcam 公開攝影機清單 https://www.twipcam.com/api/v1/cam-list.json
     （民間整合平台，彙整交通部與各縣市政府公開之 CCTV 影像）
     單筆格式：{"id", "lat", "lon", "name", "cam_url"}
  2. 逐支鏡頭頁面 https://www.twipcam.com/cam/<id>
     頁面內嵌臺北市政府 NVR 的 Low-Latency HLS 直播位址
     （https://jtmctrafficcctvN.gov.taipei/NVR/<uuid>/live.m3u8）

為什麼要多抓一次逐支頁面：
  cam-list.json 只提供 cam_url，也就是快照 JPEG。實測該快照由 CDN 快取，常見數小時
  到數天未更新，畫面等同靜止。真正的即時影像是官方 NVR 的 HLS 串流，只出現在逐支
  鏡頭頁面裡，因此必須額外解析。該端點回應 access-control-allow-origin: *，
  瀏覽器可直接播放，不需要後端轉送。

為什麼是離線產生而不是執行期抓取：
  1. 清單約 2.7 MB / 11500 筆，不該在每次請求或每次啟動時下載。
  2. 攝影機佈點是靜態資料，不隨模擬時鐘變動。
  3. 產出的對照表進版控後，Demo 與 App Runner 部署不依賴外部網路即可運作。

挑選邏輯（僅影響畫面呈現，不參與任何 SOP 判定或 ETE 數學計算）：
  1. 只保留台北市路口攝影機（id 前綴 tpe-）。
  2. 距離 = 攝影機到該路段折線各節點的最短 haversine 距離。
  3. 路名關鍵字（路名前兩字，如「光復南路」→「光復」）命中攝影機名稱者優先，
     因為同一路口會有多支不同朝向的攝影機，命中路名者才拍得到該路段。
  4. 關鍵字命中者依距離排序在前，其餘鄰近攝影機依距離補齊到 MAX_PER_SEGMENT。

用法：
    python scripts/build_camera_map.py
    python scripts/build_camera_map.py --cam-list ./camlist.json   # 用本地快取檔
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
COORDS_FILE = DATA_DIR / "segment_coordinates.json"
OUTPUT_FILE = DATA_DIR / "segment_cameras.json"

CAM_LIST_URL = "https://www.twipcam.com/api/v1/cam-list.json"
CAM_PAGE_URL = "https://www.twipcam.com/cam/{camera_id}"
SOURCE_NAME = "twipcam.com (公開 CCTV 整合平台)"
SOURCE_PAGE = "https://tw.live/city/taipeicity/"
STREAM_SOURCE_NAME = "臺北市政府交通局 CCTV (Low-Latency HLS)"

# 逐支鏡頭頁面中的官方 HLS 位址
HLS_PATTERN = re.compile(r"https://[a-z0-9.]*gov\.taipei/NVR/[0-9a-f-]+/live\.m3u8", re.I)
# 逐支頁面各約 70 KB，適度並行即可，不對來源造成壓力
SCRAPE_WORKERS = 6
BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0 Safari/537.36"
)

# 只採用台北市路口攝影機
TPE_PREFIX = "tpe-"
# 超過這個距離就不算「該路段的街景」
MAX_DISTANCE_M = 900.0
# 每個路段最多保留幾支攝影機（前端可切換）
MAX_PER_SEGMENT = 4

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """兩點球面距離（公尺）。"""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def road_keyword(road_name: str) -> str:
    """
    取路名前兩字作為比對關鍵字。
    忠孝東路四段 → 忠孝、光復南路 → 光復、基隆路地下道 → 基隆、市民大道四段 → 市民
    """
    return road_name[:2] if len(road_name) >= 2 else road_name


def load_cam_list(local_path: str | None) -> list[dict]:
    if local_path:
        raw = Path(local_path).read_text(encoding="utf-8")
    else:
        print(f"下載攝影機清單：{CAM_LIST_URL}")
        req = urllib.request.Request(
            CAM_LIST_URL, headers={"User-Agent": "city-commander-agent/2.1 (camera map builder)"}
        )
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 - 固定的 https 公開端點
            raw = resp.read().decode("utf-8")

    cams = json.loads(raw)
    if not isinstance(cams, list):
        raise ValueError("攝影機清單格式非預期（應為陣列）")
    return cams


def distance_to_segment(cam: dict, path: list[list[float]]) -> float:
    """攝影機到路段折線各節點的最短距離。"""
    return min(haversine_m(cam["lat"], cam["lon"], node[0], node[1]) for node in path)


def pick_cameras(cams: list[dict], road_name: str, path: list[list[float]]) -> list[dict]:
    keyword = road_keyword(road_name)

    scored = []
    for cam in cams:
        dist = distance_to_segment(cam, path)
        if dist > MAX_DISTANCE_M:
            continue
        name = cam.get("name", "")
        scored.append({
            "camera_id": cam["id"],
            # 清單裡的名稱形如「台北市道路 129-忠孝光復」，去掉前綴讓畫面乾淨
            "name": name.replace("台北市道路", "").strip(),
            "lat": cam["lat"],
            "lon": cam["lon"],
            "snapshot_url": cam["cam_url"],
            "distance_m": round(dist),
            "matches_road_name": keyword in name,
        })

    # 路名命中者優先，其次比距離
    scored.sort(key=lambda c: (not c["matches_road_name"], c["distance_m"]))
    return scored[:MAX_PER_SEGMENT]


def scrape_stream_url(camera_id: str) -> tuple[str, str | None]:
    """從逐支鏡頭頁面解析官方 HLS 直播位址；找不到時回 None。"""
    url = CAM_PAGE_URL.format(camera_id=camera_id)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - 固定的 https 公開端點
            html = resp.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"    ! {camera_id} 頁面取得失敗：{type(e).__name__}: {e}", file=sys.stderr)
        return camera_id, None

    found = HLS_PATTERN.search(html)
    return camera_id, (found.group(0) if found else None)


def attach_stream_urls(mapping: dict[str, dict]) -> tuple[int, int]:
    """
    為對照表內的每支鏡頭補上 HLS 直播位址。

    同一支鏡頭可能同時被多個路段選中，因此先去重再抓，避免重複請求。
    """
    unique_ids = sorted({
        cam["camera_id"]
        for entry in mapping.values()
        for cam in entry["cameras"]
    })
    if not unique_ids:
        return 0, 0

    print(f"\n解析官方 HLS 直播位址（{len(unique_ids)} 支不重複鏡頭）…")
    with ThreadPoolExecutor(max_workers=SCRAPE_WORKERS) as pool:
        resolved = dict(pool.map(scrape_stream_url, unique_ids))

    for entry in mapping.values():
        for cam in entry["cameras"]:
            stream_url = resolved.get(cam["camera_id"])
            if stream_url:
                cam["stream_url"] = stream_url
                cam["stream_type"] = "hls"

    have = sum(1 for v in resolved.values() if v)
    return have, len(unique_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description="產生路段 → 即時影像攝影機對照表")
    parser.add_argument("--cam-list", help="本地 cam-list.json 路徑（省略則從網路下載）")
    parser.add_argument(
        "--skip-streams",
        action="store_true",
        help="不解析官方 HLS 位址（僅產生快照對照表，離線或來源異動時可用）",
    )
    args = parser.parse_args()

    if not COORDS_FILE.exists():
        print(f"找不到座標檔：{COORDS_FILE}", file=sys.stderr)
        return 1

    coords = json.loads(COORDS_FILE.read_text(encoding="utf-8"))
    segments = coords.get("segments", {})

    try:
        all_cams = load_cam_list(args.cam_list)
    except Exception as e:
        print(f"取得攝影機清單失敗：{type(e).__name__}: {e}", file=sys.stderr)
        return 1

    tpe_cams = [
        c for c in all_cams
        if isinstance(c, dict)
        and str(c.get("id", "")).startswith(TPE_PREFIX)
        and isinstance(c.get("lat"), (int, float))
        and isinstance(c.get("lon"), (int, float))
        and c.get("cam_url")
    ]
    print(f"清單共 {len(all_cams)} 筆，其中台北市路口攝影機 {len(tpe_cams)} 支")

    mapping: dict[str, dict] = {}
    for seg_id, info in segments.items():
        path = info.get("path") or [info["point"]]
        picked = pick_cameras(tpe_cams, info["name"], path)
        mapping[seg_id] = {"road_name": info["name"], "cameras": picked}

        if picked:
            head = picked[0]
            flag = "路名命中" if head["matches_road_name"] else "僅鄰近"
            print(f"  {seg_id} {info['name']:<8} → {len(picked)} 支，最佳 {head['name']} ({head['distance_m']} m, {flag})")
        else:
            print(f"  {seg_id} {info['name']:<8} → 無 {MAX_DISTANCE_M:.0f} m 內的攝影機")

    stream_have = stream_total = 0
    if not args.skip_streams:
        stream_have, stream_total = attach_stream_urls(mapping)
        print(f"  取得 {stream_have}/{stream_total} 支鏡頭的直播位址")

    payload = {
        "_comment": "由 scripts/build_camera_map.py 產生，請勿手動編輯。僅供畫面呈現，不參與 SOP 判定與 ETE 計算。",
        "source": SOURCE_NAME,
        "source_page": SOURCE_PAGE,
        "source_api": CAM_LIST_URL,
        "stream_source": STREAM_SOURCE_NAME,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "max_distance_m": MAX_DISTANCE_M,
        "segments": mapping,
    }
    OUTPUT_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    covered = sum(1 for v in mapping.values() if v["cameras"])
    print(f"\n已寫入 {OUTPUT_FILE}（{covered}/{len(mapping)} 個路段有街景）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
