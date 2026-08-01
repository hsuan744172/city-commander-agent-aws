"""
Demo 用模擬街景畫面產生器。

為什麼需要這個：公開 CCTV 來源（twipcam 的台北市鏡像）實測已數小時到數天未更新，
Demo 時畫面完全靜止。本模組在後端合成會動的路口畫面，讓 MJPEG 代理有內容可送。

與 Demo 情境連動，不是隨機動畫：
  - 車流密度與車速取自該路段當下的飽和度（由 traffic_math 提供，本模組不自行計算）
  - 畫面時間戳跟著 sim_clock 走，與儀表板、事件建議書同一個時間軸
  - 飽和度越高 → 車越多、移動越慢，A 級路段看起來就是在爬

為什麼不用 Pillow：backend/Dockerfile 以 `uv sync --frozen` 安裝，新增依賴必須同步
更新 uv.lock，而部署環境未必能重新產生 lock。因此改用標準庫 zlib 手寫 PNG 編碼，
搭配 pandas 已保證存在的 numpy 做像素運算，不動依賴樹。

輸出為 PNG。multipart/x-mixed-replace 的每個片段各自帶 Content-Type，
瀏覽器同樣會逐幀替換顯示，不限於 JPEG。

本模組純屬畫面呈現，不參與 SOP 判定與 ETE 計算。
"""

from __future__ import annotations

import logging
import struct
import threading
import time
import zlib

import numpy as np

from backend import sim_clock

logger = logging.getLogger(__name__)

WIDTH, HEIGHT = 480, 270
FPS = 5.0

# 畫面配色（深色路面 + 高對比疊字，貼近實際監視器影像）
_SKY_TOP = (58, 70, 82)
_SKY_BOTTOM = (104, 116, 124)
_ROAD = (48, 50, 54)
_ROAD_EDGE = (86, 88, 92)
_KERB = (72, 76, 74)
_LANE_MARK = (196, 198, 190)
_BUILDING = (74, 80, 86)

HORIZON_Y = 96
BOTTOM_Y = HEIGHT - 6
# 路面梯形：地平線處的左右邊界，與畫面底部的左右邊界
_ROAD_TOP_L, _ROAD_TOP_R = 206, 268
_ROAD_BOT_L, _ROAD_BOT_R = 8, WIDTH - 8

# 去程 3 車道 + 對向 2 車道
_LANES_INBOUND = 3
_LANES_OUTBOUND = 2
_TOTAL_LANES = _LANES_INBOUND + _LANES_OUTBOUND

# 車輛顏色池，依鏡頭與車輛序號決定，同一支鏡頭每次看到的車色一致
_CAR_COLORS = (
    (188, 190, 194), (58, 62, 70), (168, 172, 178), (92, 96, 104),
    (140, 78, 72), (66, 92, 116), (150, 146, 132), (40, 44, 50),
)


# ---------------------------------------------------------------------------
# 5x7 點陣字型（僅疊字用，故只收 ASCII）
# ---------------------------------------------------------------------------

_GLYPHS = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("01110", "00100", "00100", "00100", "00100", "00100", "01110"),
    "J": ("00111", "00010", "00010", "00010", "00010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10011", "01111"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "11011", "10001"),
    "X": ("10001", "01010", "00100", "00100", "00100", "01010", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    ":": ("00000", "00100", "00000", "00000", "00000", "00100", "00000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
    "%": ("11001", "11010", "00010", "00100", "01000", "01011", "10011"),
    "/": ("00001", "00010", "00010", "00100", "01000", "01000", "10000"),
    "+": ("00000", "00100", "00100", "11111", "00100", "00100", "00000"),
    "(": ("00010", "00100", "01000", "01000", "01000", "00100", "00010"),
    ")": ("01000", "00100", "00010", "00010", "00010", "00100", "01000"),
    " ": ("00000",) * 7,
}
_GLYPH_W, _GLYPH_H = 5, 7


def _draw_text(buf: np.ndarray, x: int, y: int, text: str,
               color: tuple[int, int, int], scale: int = 1) -> None:
    """把 ASCII 疊字畫進像素緣衝區。無對應字形的字元以空白略過。"""
    cursor = x
    for char in text.upper():
        glyph = _GLYPHS.get(char)
        if glyph is None:
            cursor += (_GLYPH_W + 1) * scale
            continue
        for row, bits in enumerate(glyph):
            for col, bit in enumerate(bits):
                if bit != "1":
                    continue
                px, py = cursor + col * scale, y + row * scale
                if 0 <= px < WIDTH - scale and 0 <= py < HEIGHT - scale:
                    buf[py:py + scale, px:px + scale] = color
        cursor += (_GLYPH_W + 1) * scale


def _text_width(text: str, scale: int = 1) -> int:
    return len(text) * (_GLYPH_W + 1) * scale


def _fill(buf: np.ndarray, x0: int, y0: int, x1: int, y1: int,
          color: tuple[int, int, int], alpha: float = 1.0) -> None:
    """畫矩形，alpha < 1 時與底色混合。座標自動裁切到畫面內。"""
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(WIDTH, int(x1)), min(HEIGHT, int(y1))
    if x1 <= x0 or y1 <= y0:
        return
    if alpha >= 1.0:
        buf[y0:y1, x0:x1] = color
    else:
        region = buf[y0:y1, x0:x1].astype(np.float32)
        blend = region * (1 - alpha) + np.array(color, dtype=np.float32) * alpha
        buf[y0:y1, x0:x1] = blend.astype(np.uint8)


# ---------------------------------------------------------------------------
# 場景幾何
# ---------------------------------------------------------------------------


def _depth_to_y(depth: float) -> float:
    """depth 0 = 地平線（遠），1 = 畫面底部（近）。非線性以模擬透視壓縮。"""
    return HORIZON_Y + (BOTTOM_Y - HORIZON_Y) * (depth ** 1.9)


def _road_edges(y: float) -> tuple[float, float]:
    t = 0.0 if BOTTOM_Y == HORIZON_Y else (y - HORIZON_Y) / (BOTTOM_Y - HORIZON_Y)
    t = min(max(t, 0.0), 1.0)
    left = _ROAD_TOP_L + (_ROAD_BOT_L - _ROAD_TOP_L) * t
    right = _ROAD_TOP_R + (_ROAD_BOT_R - _ROAD_TOP_R) * t
    return left, right


def _lane_center(lane: int, y: float) -> float:
    left, right = _road_edges(y)
    width = (right - left) / _TOTAL_LANES
    return left + width * (lane + 0.5)


def _draw_background(buf: np.ndarray) -> None:
    # 天空漸層
    for y in range(0, HORIZON_Y):
        t = y / max(1, HORIZON_Y - 1)
        color = tuple(int(_SKY_TOP[i] + (_SKY_BOTTOM[i] - _SKY_TOP[i]) * t) for i in range(3))
        buf[y, :] = color

    # 遠景建物剪影，讓地平線不空
    skyline = ((20, 34), (52, 20), (78, 40), (112, 26), (150, 44), (300, 30),
               (340, 46), (372, 22), (410, 38), (444, 28))
    for x, h in skyline:
        _fill(buf, x, HORIZON_Y - h, x + 26, HORIZON_Y, _BUILDING)

    # 路面
    for y in range(HORIZON_Y, HEIGHT):
        left, right = _road_edges(y)
        _fill(buf, 0, y, WIDTH, y + 1, _KERB)
        _fill(buf, left, y, right, y + 1, _ROAD)
        _fill(buf, left - 1, y, left + 1, y + 1, _ROAD_EDGE)
        _fill(buf, right - 1, y, right + 1, y + 1, _ROAD_EDGE)


def _draw_lane_marks(buf: np.ndarray, phase: float) -> None:
    """車道虛線。phase 隨時間推進，產生地面往觀察者移動的錯覺。"""
    for lane in range(1, _TOTAL_LANES):
        # 去程與對向之間畫實線（分向線）
        solid = lane == _LANES_OUTBOUND
        for i in range(28):
            depth = ((i / 28.0) + phase) % 1.0
            if not solid and (i % 2 == 0):
                continue
            y = _depth_to_y(depth)
            y_next = _depth_to_y(min(1.0, depth + 0.028))
            thickness = max(1.0, 2.6 * (depth ** 1.6))
            x = _lane_center(lane, y) - (_lane_center(lane, y) - _lane_center(lane - 1, y)) * 0.5
            _fill(buf, x - thickness / 2, y, x + thickness / 2, max(y + 1, y_next), _LANE_MARK,
                  alpha=0.55 if not solid else 0.75)


def _draw_vehicle(buf: np.ndarray, lane: int, depth: float,
                  color: tuple[int, int, int], inbound: bool) -> None:
    y = _depth_to_y(depth)
    scale = 0.16 + 1.05 * (depth ** 1.7)
    left, right = _road_edges(y)
    lane_w = (right - left) / _TOTAL_LANES

    body_w = max(2.0, lane_w * 0.66)
    body_h = max(2.0, 22 * scale)
    cx = _lane_center(lane, y)

    # 車身 + 較深的車頂，遠處只剩幾個像素
    _fill(buf, cx - body_w / 2, y - body_h, cx + body_w / 2, y, color)
    roof = tuple(int(c * 0.72) for c in color)
    _fill(buf, cx - body_w * 0.36, y - body_h * 0.92, cx + body_w * 0.36, y - body_h * 0.45, roof)

    # 近處才畫燈：去程看到車尾（紅），對向看到車頭（黃白）
    if depth > 0.42:
        lamp = (198, 66, 58) if inbound else (226, 214, 168)
        lamp_w = max(1.0, body_w * 0.16)
        lamp_h = max(1.0, body_h * 0.13)
        _fill(buf, cx - body_w / 2 + lamp_w * 0.4, y - body_h * 0.34,
              cx - body_w / 2 + lamp_w * 1.4, y - body_h * 0.34 + lamp_h, lamp)
        _fill(buf, cx + body_w / 2 - lamp_w * 1.4, y - body_h * 0.34,
              cx + body_w / 2 - lamp_w * 0.4, y - body_h * 0.34 + lamp_h, lamp)

    # 地面陰影
    _fill(buf, cx - body_w * 0.55, y, cx + body_w * 0.55, y + max(1.0, 2 * scale),
          (32, 34, 36), alpha=0.5)


def _draw_signal(buf: np.ndarray, phase: float) -> None:
    """
    路口號誌。即使路段嚴重壅塞、車輛幾乎不動，燈色變化仍讓畫面有明顯活動跡象。
    """
    pole_x, pole_y = WIDTH - 62, HORIZON_Y - 54
    _fill(buf, pole_x + 8, pole_y, pole_x + 11, HORIZON_Y + 6, (58, 60, 62))
    _fill(buf, pole_x, pole_y, pole_x + 20, pole_y + 44, (38, 40, 42))

    cycle = phase % 1.0
    if cycle < 0.45:
        active = 2
    elif cycle < 0.58:
        active = 1
    else:
        active = 0
    colors = ((176, 62, 54), (188, 158, 62), (76, 172, 118))
    for i, base in enumerate(colors):
        lit = i == active
        color = base if lit else tuple(int(c * 0.28) for c in base)
        cy = pole_y + 7 + i * 13
        _fill(buf, pole_x + 5, cy, pole_x + 15, cy + 10, color)


def _draw_overlay(buf: np.ndarray, camera_name: str, road_name: str,
                  saturation: float | None, sim_time: str, blink: bool) -> None:
    # 上緣資訊條
    _fill(buf, 0, 0, WIDTH, 15, (12, 14, 16), alpha=0.62)
    _draw_text(buf, 4, 4, _ascii(camera_name)[:34], (216, 220, 222))

    stamp = sim_time
    _draw_text(buf, WIDTH - _text_width(stamp) - 5, 4, stamp, (216, 220, 222))

    # 下緣資訊條：路段與飽和度
    _fill(buf, 0, HEIGHT - 15, WIDTH, HEIGHT, (12, 14, 16), alpha=0.62)
    label = _ascii(road_name)[:26]
    _draw_text(buf, 4, HEIGHT - 11, label, (204, 208, 210))

    if saturation is not None:
        pct = f"SAT {round(saturation * 100)}%"
        # 依等級上色，與儀表板的 A/B 級判定門檻一致
        if saturation >= 0.95:
            tint = (214, 96, 88)
        elif saturation >= 0.85:
            tint = (212, 158, 78)
        else:
            tint = (128, 200, 166)
        _draw_text(buf, WIDTH - _text_width(pct) - 5, HEIGHT - 11, pct, tint)

    # LIVE 指示，閃爍讓畫面在任何情況下都有變化
    dot = (208, 74, 66) if blink else (96, 46, 44)
    _fill(buf, 6, 20, 12, 26, dot)
    _draw_text(buf, 16, 20, "LIVE", (222, 226, 228))


def _ascii(text: str) -> str:
    """疊字只支援 ASCII；無對應字形者以空白取代，避免畫出亂碼方塊。"""
    return "".join(ch if ch.isascii() and (ch.isalnum() or ch in " -:.%/+()_") else " "
                   for ch in text).strip()


def _display_label(name: str, fallback: str) -> str:
    """
    選一個畫得出來的疊字。

    手寫點陣字型只有 ASCII，中文鏡頭名稱濾掉非 ASCII 後往往只剩無意義碎片
    （「177-基隆路北往南主車道1(基隆忠孝)」會變成「177- 1( )」），這種情況改用
    鏡頭代碼，看起來才像真實監視器的疊字。
    """
    if name and all(ch.isascii() for ch in name):
        cleaned = _ascii(name)
        if cleaned:
            return cleaned
    return fallback.upper()


# ---------------------------------------------------------------------------
# PNG 編碼（標準庫 zlib，不引入影像套件）
# ---------------------------------------------------------------------------


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def _encode_png(rgb: np.ndarray) -> bytes:
    height, width, _ = rgb.shape
    # 每條掃描線前置 filter type 0
    scanlines = np.hstack([
        np.zeros((height, 1), dtype=np.uint8),
        rgb.reshape(height, width * 3),
    ])
    # level 4：Demo 走 5 fps，壓縮比與 CPU 之間取平衡
    compressed = zlib.compress(scanlines.tobytes(), 4)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", header)
            + _png_chunk(b"IDAT", compressed)
            + _png_chunk(b"IEND", b""))


# ---------------------------------------------------------------------------
# 路段狀態（唯讀取用 traffic_math 的結果，本模組不做決策運算）
# ---------------------------------------------------------------------------

_state_cache: dict[str, tuple[float, tuple[float | None, str]]] = {}
_state_lock = threading.Lock()
_STATE_TTL = 2.0


def _segment_state(segment_id: str) -> tuple[float | None, str]:
    """取該路段當下飽和度與路名。取不到時回 (None, "")，畫面照樣能產生。"""
    now = time.monotonic()
    with _state_lock:
        hit = _state_cache.get(segment_id)
        if hit and now - hit[0] < _STATE_TTL:
            return hit[1]

    result: tuple[float | None, str] = (None, "")
    try:
        from backend.agents.traffic_math import _get_time_slice, _load_traffic_flow

        latest, _ = _get_time_slice(_load_traffic_flow(), None, key_col="Segment_ID")
        row = latest[latest["Segment_ID"] == segment_id]
        if not row.empty:
            record = row.iloc[0]
            result = (float(record["Saturation_Score"]), str(record["Road_Name"]))
    except Exception as e:
        logger.debug(f"模擬街景取路段狀態失敗 {segment_id}: {type(e).__name__}: {e}")

    with _state_lock:
        _state_cache[segment_id] = (now, result)
    return result


# ---------------------------------------------------------------------------
# 對外介面
# ---------------------------------------------------------------------------


def render(segment_id: str, camera_id: str, camera_name: str = "") -> bytes:
    """
    合成一幀模擬街景，回傳 PNG bytes。

    畫面內容由「當下時間」與「該路段飽和度」決定，因此同一時刻的所有訂閱者
    看到相同畫面，且飽和度越高車越多、移動越慢。
    """
    saturation, road_name = _segment_state(segment_id)
    level = 0.5 if saturation is None else min(max(saturation, 0.0), 1.0)

    # 飽和度 → 車輛數與車速。壅塞時保留最低速度，畫面不會完全靜止。
    car_count = int(round(4 + 20 * level))
    speed = 0.30 * (1.0 - level) + 0.022

    now = time.time()
    # 鏡頭代碼決定車輛配置，同一支鏡頭的畫面在重連後保持一致
    seed = (abs(hash((segment_id, camera_id))) % 9973) or 7
    rng = np.random.default_rng(seed)

    buf = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    _draw_background(buf)
    _draw_lane_marks(buf, phase=(now * speed * 0.6) % 1.0)
    _draw_signal(buf, phase=(now / 24.0) % 1.0)

    lanes = rng.integers(0, _TOTAL_LANES, size=car_count)
    offsets = rng.random(car_count)
    colors = rng.integers(0, len(_CAR_COLORS), size=car_count)
    # 同車道車輛速度略有差異，看起來才不像整排平移
    jitter = 0.82 + 0.36 * rng.random(car_count)

    # 由遠而近繪製，近處車輛自然覆蓋遠處
    vehicles = []
    for i in range(car_count):
        lane = int(lanes[i])
        inbound = lane >= _LANES_OUTBOUND
        travel = now * speed * float(jitter[i])
        depth = ((offsets[i] + travel) if inbound else (offsets[i] - travel)) % 1.0
        vehicles.append((depth, lane, _CAR_COLORS[int(colors[i])], inbound))
    vehicles.sort(key=lambda v: v[0])

    for depth, lane, color, inbound in vehicles:
        _draw_vehicle(buf, lane, depth, color, inbound)

    _draw_overlay(
        buf,
        camera_name=camera_name or camera_id,
        road_name=road_name or segment_id,
        saturation=saturation,
        sim_time=sim_clock.now_str(),
        blink=int(now * 2) % 2 == 0,
    )

    return _encode_png(buf)
