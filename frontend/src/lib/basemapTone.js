/**
 * 底圖降彩 — 把 OpenFreeMap 向量圖磚的地面配色壓下去
 *
 * 底圖的黃色幹道、綠色公園、藍色水域彩度很高，會和我們自己疊上去的路段分級色打架。
 * 這裡在地圖載入時走過底圖每一個圖層，把顏色降彩並往頁面底色淡化，
 * 讓底圖退成灰階襯底，路網線與人流站點才是視覺主角。
 *
 * 重要：只處理「底圖自帶」的圖層，必須在 addLayer 加入 traffic-roads / stations
 * 之前呼叫，否則我們自己的分級色也會被一起洗掉。
 */

export const BASEMAP_TONE = {
  /** 底圖彩度：1 = 原樣，0 = 完全灰階 */
  saturation: 0.3,
  /** 往 fadeTarget 淡化的比例：0 = 不淡化，1 = 整片變成 fadeTarget */
  fade: 0.35,
  /** 淡化目標色，預設用 App 的頁面底色，底圖會融進背景 */
  fadeTarget: "#FBFEFD",
};

/** 各圖層型別要處理的顏色類 paint 屬性 */
const COLOR_PAINT_PROPS = {
  background: ["background-color"],
  fill: ["fill-color", "fill-outline-color"],
  line: ["line-color"],
  symbol: ["text-color", "text-halo-color", "icon-color", "icon-halo-color"],
  circle: ["circle-color", "circle-stroke-color"],
  "fill-extrusion": ["fill-extrusion-color"],
};

const clamp01 = (n) => Math.max(0, Math.min(1, n));
const clampByte = (n) => Math.max(0, Math.min(255, Math.round(n)));

/** "50%" → 0.5；"0.5" → 0.5 */
function ratio(token) {
  const value = parseFloat(token);
  if (Number.isNaN(value)) return 1;
  return token.trim().endsWith("%") ? value / 100 : value;
}

/** rgb() 的單一通道：支援 0~255 與百分比 */
function channel(token) {
  const value = parseFloat(token);
  if (Number.isNaN(value)) return 0;
  return token.trim().endsWith("%") ? (value / 100) * 255 : value;
}

function hslToRgb(h, s, l, a) {
  const hue = ((h % 360) + 360) % 360;
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((hue / 60) % 2) - 1));
  const m = l - c / 2;
  const table = [
    [c, x, 0], [x, c, 0], [0, c, x],
    [0, x, c], [x, 0, c], [c, 0, x],
  ];
  const [r, g, b] = table[Math.floor(hue / 60) % 6];
  return { r: (r + m) * 255, g: (g + m) * 255, b: (b + m) * 255, a };
}

/**
 * 解析 hex / rgb / rgba / hsl / hsla。
 * 刻意不支援 CSS 命名色：底圖樣式的 match 運算式常拿 "grass"、"wood" 這類
 * 字串當比對值，若連命名色一起解析會誤把資料值當顏色改掉。
 */
export function parseColor(value) {
  if (typeof value !== "string") return null;
  const text = value.trim();

  const hex = /^#([0-9a-f]+)$/i.exec(text);
  if (hex) {
    const digits = hex[1];
    if (digits.length === 3 || digits.length === 4) {
      const [r, g, b, alpha] = [...digits].map((c) => parseInt(c + c, 16));
      return { r, g, b, a: digits.length === 4 ? alpha / 255 : 1 };
    }
    if (digits.length === 6 || digits.length === 8) {
      const at = (i) => parseInt(digits.slice(i, i + 2), 16);
      return { r: at(0), g: at(2), b: at(4), a: digits.length === 8 ? at(6) / 255 : 1 };
    }
    return null;
  }

  const fn = /^(rgba?|hsla?)\(([^)]+)\)$/i.exec(text);
  if (!fn) return null;
  const parts = fn[2].split(/[,/\s]+/).filter(Boolean);
  if (parts.length < 3) return null;

  const alpha = parts.length > 3 ? clamp01(ratio(parts[3])) : 1;
  if (fn[1].toLowerCase().startsWith("rgb")) {
    return { r: channel(parts[0]), g: channel(parts[1]), b: channel(parts[2]), a: alpha };
  }
  return hslToRgb(parseFloat(parts[0]), clamp01(ratio(parts[1])), clamp01(ratio(parts[2])), alpha);
}

/**
 * 單一顏色降彩：先往同亮度灰階混合（抽彩度），再往 fadeTarget 淡化。
 * 透明度原封不動保留，否則底圖的半透明遮罩層會整片變實心。
 */
export function toneColor(value) {
  const color = parseColor(value);
  if (!color) return null;

  const { saturation, fade } = BASEMAP_TONE;
  const target = parseColor(BASEMAP_TONE.fadeTarget) ?? { r: 255, g: 255, b: 255, a: 1 };
  const gray = 0.299 * color.r + 0.587 * color.g + 0.114 * color.b;
  const mix = (c, t) => {
    const desaturated = gray + (c - gray) * saturation;
    return clampByte(desaturated + (t - desaturated) * fade);
  };

  const alpha = Math.round(color.a * 1000) / 1000;
  return `rgba(${mix(color.r, target.r)}, ${mix(color.g, target.g)}, ${mix(color.b, target.b)}, ${alpha})`;
}

/**
 * paint 值可能是純色字串、運算式陣列，或舊式 { stops } 物件，三種都要遞迴處理。
 * 陣列裡的運算子（"interpolate"、"get"…）解析不出顏色，會原樣留下。
 */
export function toneValue(value) {
  if (typeof value === "string") return toneColor(value) ?? value;
  if (Array.isArray(value)) return value.map((item) => toneValue(item));
  if (value && typeof value === "object") {
    if (Array.isArray(value.stops)) {
      return {
        ...value,
        stops: value.stops.map(([stop, output]) => [stop, toneValue(output)]),
      };
    }
    return value;
  }
  return value;
}

/**
 * 對目前樣式的所有圖層套用降彩。
 * @param {import("maplibre-gl").Map} map
 */
export function applyBasemapTone(map) {
  const { saturation, fade } = BASEMAP_TONE;
  if (saturation >= 1 && fade <= 0) return;

  const layers = map.getStyle()?.layers ?? [];
  for (const layer of layers) {
    const props = COLOR_PAINT_PROPS[layer.type];
    if (!props) continue;
    for (const prop of props) {
      try {
        const current = map.getPaintProperty(layer.id, prop);
        if (current === undefined || current === null) continue;
        const toned = toneValue(current);
        if (toned !== current) map.setPaintProperty(layer.id, prop, toned);
      } catch (error) {
        // 單一圖層降彩失敗不該讓整張地圖掛掉，維持底圖原色繼續跑。
        console.warn(`[basemapTone] ${layer.id} / ${prop} 降彩略過:`, error);
      }
    }
  }
}
