/**
 * 地圖線條外觀設定 — 透明度／飽和度／粗細的單一調整點
 *
 * 儀表板的 MapLibre 3D 路網圖（CityMap3D）與事件頁的 Leaflet 疏散圖（IncidentMap）
 * 共用這裡的數值。想讓路線變淡、變細或彩度收斂，只改 MAP_LINE_STYLE 即可，
 * 不需要進到各元件的 paint / pathOptions 逐一改。
 *
 * 註：MapLibre 與 Leaflet 的線條畫在 canvas / SVG 上，取不到 CSS 變數，
 * 因此分級色以 hex 定義，但集中在本檔案，避免散落在元件裡各寫一份。
 */

export const MAP_LINE_STYLE = {
  /** 彩度：1 = 原始分級色，0 = 同亮度灰階。0.6~0.8 之間視覺最收斂 */
  saturation: 0.72,

  /** 透明度：0 = 全透明，1 = 不透明 */
  opacity: {
    fill: 0.78, // 路面主體（依分級著色）
    casing: 0.4, // 路面深色描邊
    selected: 0.42, // 選中路段的外圈 highlight
    dots: 0.8, // 沿路移動的車流光點
    affected: 0.8, // 事件圖：事故路段
    primary: 0.85, // 事件圖：主疏散路段
    secondary: 0.6, // 事件圖：次要疏散路段
  },

  /** 粗細（px） */
  width: {
    // MapLibre：依 zoom 13 / 16 / 18 三個停點線性內插
    fill: { z13: 4, z16: 9, z18: 14 },
    casing: { z13: 6, z16: 12, z18: 18 },
    selected: { z13: 9, z16: 16, z18: 24 },
    // Leaflet：固定寬度
    affected: 5,
    primary: 4,
    secondary: 3,
  },

  /**
   * 點擊命中區 = 描邊寬度 × scale，並保有最小寬度。
   * 由描邊寬度換算而來，路面調細時命中區不會跟著縮到點不到。
   */
  hitArea: { scale: 1.8, minWidth: 14 },
};

/** 路段分級基色（套用彩度前） */
const LEVEL_BASE_COLOR = {
  A: "#D94F4F",
  B: "#C8922A",
  NORMAL: "#3A9E74",
};

/** 事件圖路線基色（套用彩度前） */
const ROUTE_BASE_COLOR = {
  affected: "#DC2626",
  primary: "#16A34A",
  secondary: "#2563EB",
};

/** 選中路段外圈（accent 色） */
export const SELECTED_OUTLINE_COLOR = "#BA56DE";

/**
 * 依 saturation 把顏色往「同亮度灰階」混合。
 * 用感知亮度當灰階基準，只抽彩度不動明暗，線條不會因為降彩度而看起來變淡或變重。
 */
export function desaturate(hex, saturation = MAP_LINE_STYLE.saturation) {
  const match = /^#?([0-9a-f]{6})$/i.exec(String(hex));
  if (!match || saturation >= 1) return hex;

  const value = parseInt(match[1], 16);
  const rgb = [(value >> 16) & 255, (value >> 8) & 255, value & 255];
  const gray = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2];
  const clamp = (n) => Math.max(0, Math.min(255, Math.round(n)));

  return `#${rgb
    .map((c) => clamp(gray + (c - gray) * saturation).toString(16).padStart(2, "0"))
    .join("")}`;
}

/** 路面描邊色（灰藍，同樣走 desaturate 保持一致） */
export const CASING_COLOR = desaturate("#5A6472");

/**
 * 後端分級 → 線條顏色（門檻只由後端規則決定，前端只負責上色）
 * A 級：紅色；B 級：橘黃；其餘：綠色
 */
export function levelColor(level) {
  return desaturate(LEVEL_BASE_COLOR[level] ?? LEVEL_BASE_COLOR.NORMAL);
}

/** 事件圖線條顏色：affected / primary / secondary */
export function routeColor(kind) {
  return desaturate(ROUTE_BASE_COLOR[kind] ?? ROUTE_BASE_COLOR.secondary);
}

/** 由 { z13, z16, z18 } 產生 MapLibre 的 zoom 內插寬度運算式 */
export function zoomWidth(stops, { scale = 1, minWidth = 0 } = {}) {
  const at = (value) => Math.max(value * scale, minWidth);
  return [
    "interpolate",
    ["linear"],
    ["zoom"],
    13, at(stops.z13),
    16, at(stops.z16),
    18, at(stops.z18),
  ];
}

/** 命中區寬度：由描邊寬度換算，確保細線也點得到 */
export function hitAreaWidth() {
  const { scale, minWidth } = MAP_LINE_STYLE.hitArea;
  return zoomWidth(MAP_LINE_STYLE.width.casing, { scale, minWidth });
}
