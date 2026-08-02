import { useEffect, useRef, useState } from "react";
import { Map as MaplibreMap, NavigationControl, Popup, setWorkerUrl } from "maplibre-gl";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  MAP_LINE_STYLE,
  CASING_COLOR,
  SELECTED_OUTLINE_COLOR,
  levelColor,
  zoomWidth,
  hitAreaWidth,
} from "../lib/mapLineStyle";
import { applyBasemapTone } from "../lib/basemapTone";
import { createCameraDirector } from "../lib/mapCamera";
import { Crosshair, Hand, Orbit } from "lucide-react";
// 路段與站點座標移到 lib/segmentGeometry，與事件注入頁的疏散圖共用同一份 OSM 座標。
import { SEGMENT_COORDS, STATION_COORDS, STATION_NAMES } from "../lib/segmentGeometry";

// MapLibre 6 的預設 worker URL 依賴 import.meta.url；經 Vite bundle 後會誤指向
// /assets/maplibre-gl-worker.mjs，正式映像並沒有該檔案。明確交給 Vite 打包 worker，
// 產出帶 content hash 的同源資產，避免 ECS 上向量圖磚與 3D 建築靜默停止渲染。
setWorkerUrl(maplibreWorkerUrl);

/**
 * 建立站點 GeoJSON — 結合靜態座標與動態人流資料
 */
function buildStationGeoJSON(stations = [], roamingThreshold = Number.POSITIVE_INFINITY) {
  const stationDataMap = new Map(stations.map((s) => [s.bs_id, s]));
  const features = Object.entries(STATION_COORDS).map(([id, coords]) => {
    const data = stationDataMap.get(id);
    const hasData = data && data.user_count > 0;

    // 半徑：無資料=6, 有資料依 user_count 線性映射 6~22
    let radius = 6;
    if (hasData) {
      const count = data.user_count;
      if (count >= 45000) radius = 22;
      else if (count >= 30000) radius = 18;
      else if (count >= 15000) radius = 12;
      else if (count >= 5000) radius = 8;
      else radius = 6;
    }

    // 顏色：無資料=白色, 有資料依 growth_rate
    let fillColor = "#ffffff";
    let strokeColor = "#94a3b8";
    if (hasData) {
      const rate = data.growth_rate;
      if (rate >= 0.5) fillColor = "#dc2626";
      else if (rate >= 0.2) fillColor = "#f97316";
      else if (rate >= 0) fillColor = "#22c55e";
      else if (rate >= -0.3) fillColor = "#3b82f6";
      else fillColor = "#6366f1";
      strokeColor = "#ffffff";
    }

    return {
      type: "Feature",
      properties: {
        bs_id: id,
        name: data?.location_name || STATION_NAMES[id] || id,
        user_count: data?.user_count ?? 0,
        growth_rate: data?.growth_rate ?? 0,
        // 後端統一以 0~1 表示漫遊率，顯示字串另外給。
        // 原本這裡假設是 0~100 並直接和 30 比較，換算一改就會靜默失準；
        // 門檻也改由後端 /api/status 的 thresholds 提供，不在前端寫死。
        roaming_user_pct: data?.roaming_user_pct ?? 0,
        roaming_display:
          data?.roaming_user_pct_display ??
          `${Math.round((data?.roaming_user_pct ?? 0) * 100)}%`,
        stay_time_avg: data?.stay_time_avg ?? 0,
        has_roaming_alert:
          data?.exceeds_sop6_threshold ?? (data?.roaming_user_pct ?? 0) >= roamingThreshold
            ? 1
            : 0,
        radius: radius,
        fill_color: fillColor,
        stroke_color: strokeColor,
      },
      geometry: {
        type: "Point",
        coordinates: coords,
      },
    };
  });
  return { type: "FeatureCollection", features };
}

/**
 * 沿 LineString 插值取得某個進度 (0~1) 的座標點
 */
function interpolateAlongLine(coords, t) {
  if (!coords || coords.length < 2) return null;
  if (t <= 0) return coords[0];
  if (t >= 1) return coords[coords.length - 1];

  let totalLen = 0;
  const segLens = [];
  for (let i = 1; i < coords.length; i++) {
    const dx = coords[i][0] - coords[i - 1][0];
    const dy = coords[i][1] - coords[i - 1][1];
    const len = Math.sqrt(dx * dx + dy * dy);
    segLens.push(len);
    totalLen += len;
  }
  if (totalLen === 0) return coords[0];

  const targetDist = t * totalLen;
  let accumulated = 0;
  for (let i = 0; i < segLens.length; i++) {
    if (accumulated + segLens[i] >= targetDist) {
      const ratio = (targetDist - accumulated) / segLens[i];
      return [
        coords[i][0] + ratio * (coords[i + 1][0] - coords[i][0]),
        coords[i][1] + ratio * (coords[i + 1][1] - coords[i][1]),
      ];
    }
    accumulated += segLens[i];
  }
  return coords[coords.length - 1];
}

/**
 * 將一條 LineString 座標往垂直方向偏移 offsetMeters 公尺
 * 正值偏左（面對行進方向），負值偏右
 */
function offsetLineCoords(coords, offsetMeters) {
  if (!coords || coords.length < 2) return coords;
  const offsetDeg = offsetMeters / 111320; // 粗略：1度 ≈ 111320m
  const result = [];

  for (let i = 0; i < coords.length; i++) {
    let nx = 0, ny = 0;

    if (i === 0) {
      // 第一個點：用第一段的法線
      const dx = coords[1][0] - coords[0][0];
      const dy = coords[1][1] - coords[0][1];
      const len = Math.sqrt(dx * dx + dy * dy) || 1;
      nx = -dy / len;
      ny = dx / len;
    } else if (i === coords.length - 1) {
      // 最後一個點：用最後一段的法線
      const dx = coords[i][0] - coords[i - 1][0];
      const dy = coords[i][1] - coords[i - 1][1];
      const len = Math.sqrt(dx * dx + dy * dy) || 1;
      nx = -dy / len;
      ny = dx / len;
    } else {
      // 中間點：前後兩段法線平均
      const dx1 = coords[i][0] - coords[i - 1][0];
      const dy1 = coords[i][1] - coords[i - 1][1];
      const len1 = Math.sqrt(dx1 * dx1 + dy1 * dy1) || 1;
      const dx2 = coords[i + 1][0] - coords[i][0];
      const dy2 = coords[i + 1][1] - coords[i][1];
      const len2 = Math.sqrt(dx2 * dx2 + dy2 * dy2) || 1;
      nx = (-dy1 / len1 + -dy2 / len2) / 2;
      ny = (dx1 / len1 + dx2 / len2) / 2;
      const nlen = Math.sqrt(nx * nx + ny * ny) || 1;
      nx /= nlen;
      ny /= nlen;
    }

    result.push([
      coords[i][0] + nx * offsetDeg,
      coords[i][1] + ny * offsetDeg,
    ]);
  }
  return result;
}

// 預計算每條路段的正向/反向偏移座標（偏移約 5 公尺）
const OFFSET_METERS = 5;
const SEGMENT_COORDS_FWD = {};
const SEGMENT_COORDS_REV = {};
for (const [id, coords] of Object.entries(SEGMENT_COORDS)) {
  SEGMENT_COORDS_FWD[id] = offsetLineCoords(coords, OFFSET_METERS);
  SEGMENT_COORDS_REV[id] = offsetLineCoords([...coords].reverse(), -OFFSET_METERS);
}

/**
 * 將後端 segments 資料轉換為雙向道路 GeoJSON
 * 使用預計算的偏移座標（不依賴 line-offset）
 */
function buildRoadGeoJSON(segments, selectedId = null) {
  const features = [];
  for (const seg of segments) {
    const fwdCoords = SEGMENT_COORDS_FWD[seg.segment_id];
    const revCoords = SEGMENT_COORDS_REV[seg.segment_id];
    if (!fwdCoords) continue;
    const props = {
      segment_id: seg.segment_id,
      road_name: seg.road_name,
      saturation_score: seg.saturation_score,
      avg_speed: seg.avg_speed,
      vehicle_count: seg.vehicle_count,
      level: seg.level,
      lane_status: seg.lane_status,
      color: levelColor(seg.level),
      selected: seg.segment_id === selectedId ? 1 : 0,
    };
    // 正向
    features.push({
      type: "Feature",
      properties: { ...props, direction: "forward" },
      geometry: { type: "LineString", coordinates: fwdCoords },
    });
    // 反向
    if (revCoords) {
      features.push({
        type: "Feature",
        properties: { ...props, direction: "reverse" },
        geometry: { type: "LineString", coordinates: revCoords },
      });
    }
  }
  return { type: "FeatureCollection", features };
}

/**
 * 把聚焦目標換算成地圖座標。
 * 路段取線段中點（不是端點，端點通常落在路口外），站點直接取座標。
 */
function resolveFocusCenter(target) {
  if (!target) return null;
  if (target.stationId && STATION_COORDS[target.stationId]) {
    return STATION_COORDS[target.stationId];
  }
  const coords = SEGMENT_COORDS[target.segmentId];
  if (!coords) return null;
  return interpolateAlongLine(coords, 0.5);
}

/**
 * CityMap3D — 使用 MapLibre GL JS 建立 3D 城市地圖
 * - OpenFreeMap 向量圖磚 + 3D 建築
 * - 道路線依飽和度即時漸變色
 * - 串接後端 /api/status 自動刷新
 */
export default function CityMap3D({
  segments = [],
  stations = [],
  selectedSegmentId = null,
  onSegmentClick,
  thresholds = null,
  focusTarget = null,
  className = "",
}) {
  const mapContainer = useRef(null);
  const mapRef = useRef(null);
  const popupRef = useRef(null);
  const directorRef = useRef(null);
  const [mapLoaded, setMapLoaded] = useState(false);
  const [mapError, setMapError] = useState("");
  // 自動導播狀態：idle / flying / orbiting / held / released
  const [cameraState, setCameraState] = useState("idle");
  const onSegmentClickRef = useRef(onSegmentClick);
  onSegmentClickRef.current = onSegmentClick;
  // 記住最後一次的聚焦目標，指揮官接手後仍可按「重新聚焦」回到事件點
  const lastFocusRef = useRef(null);

  // 初始化地圖
  useEffect(() => {
    if (mapRef.current || !mapContainer.current) return;

    const probeCanvas = document.createElement("canvas");
    if (!probeCanvas.getContext("webgl2")) {
      setMapError("Chrome 目前無法使用 WebGL 2，3D 地圖已暫停顯示。");
      return;
    }

    let map;
    try {
      map = new MaplibreMap({
        container: mapContainer.current,
        style: "https://tiles.openfreemap.org/styles/bright",
        center: [121.5580, 25.0400], // 信義計畫區中心
        zoom: 14.5,
        pitch: 50,
        bearing: -17.6,
        canvasContextAttributes: { antialias: true },
      });
      mapRef.current = map;
      setMapError("");
    } catch (error) {
      console.error("[CityMap3D] Map initialization error:", error);
      setMapError("3D 地圖初始化失敗，其他交控資訊仍可正常使用。");
      return;
    }

    let didLoad = false;
    const handleMapError = (event) => {
      const message = String(event?.error?.message || event?.error || "未知錯誤");
      console.error("[CityMap3D] MapLibre error:", message, event?.error || event);

      // MapLibre 會為單一圖磚的暫時失敗發出 error；地圖已載入後不應因此遮住整張圖。
      // Worker、style 與首次載入錯誤則是致命的，必須明確呈現，不能再留下無訊息空白。
      if (
        !didLoad ||
        /worker|dynamically imported|style.*load|failed to fetch/i.test(message)
      ) {
        setMapError("3D 地圖資源載入失敗，請重新整理；若問題持續，請聯絡系統管理員。");
      }
    };

    map.on("error", handleMapError);
    map.addControl(new NavigationControl(), "top-right");

    map.on("load", () => {
      didLoad = true;
      setMapError("");
      try {
      // --- 底圖降彩 ---
      // 必須在加入任何自訂圖層之前執行，此時樣式裡只有底圖圖層，
      // 才不會連我們的路段分級色與站點色一起洗掉。
      applyBasemapTone(map);

      // --- 3D 建築圖層（非關鍵增強，失敗不得阻斷路網） ---
      try {
        const layers = map.getStyle().layers || [];
        const labelLayer = layers.find(
          (layer) => layer.type === "symbol" && layer.layout?.["text-field"]
        );

        // 隱藏底圖所有 symbol 圖層（POI、路名、門牌全消失），
        // 只留建築輪廓與我們自己疊上去的路段線、站點圓。
        for (const layer of layers) {
          if (layer.type === "symbol") {
            map.setLayoutProperty(layer.id, "visibility", "none");
          }
        }

        // bright 樣式已提供 openmaptiles source，直接重用，避免重複 source ID。
        if (map.getSource("openmaptiles") && !map.getLayer("3d-buildings")) {
          map.addLayer(
            {
              id: "3d-buildings",
              source: "openmaptiles",
              "source-layer": "building",
              type: "fill-extrusion",
              minzoom: 14,
              filter: ["!=", ["get", "hide_3d"], true],
              paint: {
                "fill-extrusion-color": [
                  "interpolate",
                  ["linear"],
                  ["get", "render_height"],
                  0, "#e0e0e0",
                  50, "#c0c8d4",
                  150, "#8fa4bd",
                  300, "#6b8cae",
                ],
                "fill-extrusion-height": [
                  "interpolate",
                  ["linear"],
                  ["zoom"],
                  14, 0,
                  15.5, ["get", "render_height"],
                ],
                "fill-extrusion-base": ["get", "render_min_height"],
                "fill-extrusion-opacity": 0.75,
              },
            },
            labelLayer?.id
          );
        }
      } catch (error) {
        console.warn("[CityMap3D] 3D buildings unavailable; continuing with roads:", error);
      }

      // --- 路網資料源與圖層 ---
      map.addSource("traffic-roads", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });

      // 隱形寬線：用於擴大點擊/hover 的命中區域
      map.addLayer({
        id: "traffic-roads-hitarea",
        type: "line",
        source: "traffic-roads",
        paint: {
          "line-color": "#000000",
          "line-opacity": 0.01,
          // 命中區域需覆蓋加寬後的路面，否則點擊會落在路面上卻沒反應。
          // 寬度由 MAP_LINE_STYLE.width.casing 換算，路面調細時命中區同步收斂但保有下限。
          "line-width": hitAreaWidth(),
        },
        layout: {
          "line-cap": "round",
          "line-join": "round",
        },
      });

      // 單選路段的外圈highlight（最寬，僅選中時出現）
      map.addLayer({
        id: "traffic-roads-selected-outline",
        type: "line",
        source: "traffic-roads",
        filter: ["==", ["get", "selected"], 1],
        paint: {
          "line-color": SELECTED_OUTLINE_COLOR,
          "line-width": zoomWidth(MAP_LINE_STYLE.width.selected),
          "line-blur": 0,
          "line-opacity": MAP_LINE_STYLE.opacity.selected,
        },
        layout: {
          "line-cap": "round",
          "line-join": "round",
        },
      });

      // 路面描邊（深色 casing，比路面寬，做出實體道路的邊界）
      map.addLayer({
        id: "traffic-roads-casing",
        type: "line",
        source: "traffic-roads",
        paint: {
          "line-color": CASING_COLOR,
          "line-width": zoomWidth(MAP_LINE_STYLE.width.casing),
          "line-blur": 0,
          "line-opacity": MAP_LINE_STYLE.opacity.casing,
        },
        layout: {
          "line-cap": "round",
          "line-join": "round",
        },
      });

      // 路面主體（依後端分級著色的粗實線）
      map.addLayer({
        id: "traffic-roads-fill",
        type: "line",
        source: "traffic-roads",
        paint: {
          "line-color": ["get", "color"],
          "line-width": zoomWidth(MAP_LINE_STYLE.width.fill),
          "line-blur": 0,
          "line-opacity": MAP_LINE_STYLE.opacity.fill,
        },
        layout: {
          "line-cap": "round",
          "line-join": "round",
        },
      });

      // --- 動態光點（沿路移動） ---
      map.addSource("traffic-dots", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });

      map.addLayer({
        id: "traffic-dots-layer",
        type: "circle",
        source: "traffic-dots",
        paint: {
          "circle-radius": [
            "interpolate", ["linear"], ["zoom"],
            13, 1.5,
            16, 3,
            18, 5,
          ],
          "circle-color": "#ffffff",
          "circle-blur": 0,
          "circle-opacity": MAP_LINE_STYLE.opacity.dots,
        },
      });

      // --- 路段標籤 ---
      try {
        map.addLayer({
          id: "traffic-roads-labels",
          type: "symbol",
          source: "traffic-roads",
          layout: {
            "symbol-placement": "line-center",
            "text-field": ["get", "road_name"],
            "text-size": 12,
            "text-font": ["Noto Sans Regular"],
            "text-allow-overlap": false,
            "text-ignore-placement": false,
          },
          paint: {
            "text-color": "#1a1a2e",
            "text-halo-color": "rgba(255,255,255,0.9)",
            "text-halo-width": 2,
          },
        });
      } catch (e) { console.warn("[CityMap3D] road labels failed:", e); }

      // --- 人流密度觀測站標記 ---
      map.addSource("stations", {
        type: "geojson",
        data: buildStationGeoJSON(),
      });

      // 站點光暈（大半徑模糊圓，模擬照亮附近建築）
      map.addLayer({
        id: "stations-glow",
        type: "circle",
        source: "stations",
        paint: {
          "circle-radius": 60,
          "circle-color": ["get", "fill_color"],
          "circle-blur": 1,
          "circle-opacity": 0.15,
        },
      });

      // 站點圓圈（固定紫色，收到資料後由 useEffect 更新）
      map.addLayer({
        id: "stations-circle",
        type: "circle",
        source: "stations",
        paint: {
          "circle-radius": ["get", "radius"],
          "circle-color": ["get", "fill_color"],
          "circle-stroke-color": ["get", "stroke_color"],
          "circle-stroke-width": 2,
          "circle-opacity": 0.9,
        },
      });

      // 站點名稱標籤
      try {
        map.addLayer({
          id: "stations-labels",
          type: "symbol",
          source: "stations",
          layout: {
            "text-field": ["get", "name"],
            "text-size": 11,
            "text-font": ["Noto Sans Regular"],
            "text-offset": [0, 1.8],
            "text-anchor": "top",
            "text-allow-overlap": false,
          },
          paint: {
            "text-color": "#4338ca",
            "text-halo-color": "rgba(255,255,255,0.9)",
            "text-halo-width": 1.5,
          },
        });
      } catch (e) { console.warn("[CityMap3D] station labels failed:", e); }

      // 站點 hover popup
      map.on("mouseenter", "stations-circle", (e) => {
        map.getCanvas().style.cursor = "pointer";
        if (!e.features?.length) return;
        const props = e.features[0].properties;
        const roamingAlert = props.has_roaming_alert === 1
          ? '<div style="color:#f59e0b;font-weight:bold;margin-top:4px">漫遊率 ≥ 30%，須多語通報</div>'
          : "";
        const rateLabel = props.growth_rate > 0 ? `+${props.growth_rate}` : `${props.growth_rate}`;
        const html = `
          <div style="font-family:sans-serif;font-size:13px;line-height:1.6;min-width:160px">
            <strong style="font-size:14px">${props.name}</strong>
            <div style="margin-top:4px">人流：<b>${Number(props.user_count).toLocaleString()}</b> 人</div>
            <div>增長率：<b>${rateLabel}</b></div>
            <div>漫遊率：${props.roaming_display}</div>
            <div style="color:#666;font-size:11px">平均停留 ${props.stay_time_avg} 分鐘</div>
            ${roamingAlert}
          </div>
        `;
        if (popupRef.current) {
          popupRef.current.setLngLat(e.lngLat).setHTML(html);
        } else {
          popupRef.current = new Popup({ closeButton: false, closeOnClick: false, offset: 12 })
            .setLngLat(e.lngLat).setHTML(html).addTo(map);
        }
      });
      map.on("mouseleave", "stations-circle", () => {
        map.getCanvas().style.cursor = "";
        if (popupRef.current) { popupRef.current.remove(); popupRef.current = null; }
      });

      // --- Popup 互動 (使用 hitarea 圖層偵測) ---
      map.on("mouseenter", "traffic-roads-hitarea", () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "traffic-roads-hitarea", () => {
        map.getCanvas().style.cursor = "";
        if (popupRef.current) {
          popupRef.current.remove();
          popupRef.current = null;
        }
      });
      map.on("mousemove", "traffic-roads-hitarea", (e) => {
        if (!e.features?.length) return;
        const props = e.features[0].properties;
        const score = Math.round(props.saturation_score * 100);
        const levelText = props.level === "A" ? "A 級癱瘓" : props.level === "B" ? "B 級壅擠" : "正常";
        // 級別色點沿用圖例與線條的同一組分級色，不另外用符號裝飾
        const levelDot =
          `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;` +
          `background:${levelColor(props.level)};margin-right:5px"></span>`;

        const html = `
          <div style="font-family:sans-serif;font-size:13px;line-height:1.6;min-width:160px">
            <strong style="font-size:14px">${props.road_name}</strong>
            <div style="margin-top:4px">${levelDot}${levelText}</div>
            <div>飽和度：<b>${score}%</b></div>
            <div>平均時速：${props.avg_speed} km/h</div>
            <div>車流量：${props.vehicle_count} 輛</div>
            <div style="color:#888;font-size:11px;margin-top:4px">點擊查看事件處置與建議書</div>
          </div>
        `;

        if (popupRef.current) {
          popupRef.current.setLngLat(e.lngLat).setHTML(html);
        } else {
          popupRef.current = new Popup({
            closeButton: false,
            closeOnClick: false,
            offset: 10,
            // 提示框不可吃掉滑鼠事件，否則會擋住路段點擊
            className: "cc-map-popup",
          })
            .setLngLat(e.lngLat)
            .setHTML(html)
            .addTo(map);
        }
      });

      // --- 點擊路段：跳往該路段的事件處置與建議書 ---
      map.on("click", "traffic-roads-hitarea", (e) => {
        if (!e.features?.length) return;
        const props = e.features[0].properties;
        // 關閉 popup 避免干擾
        if (popupRef.current) {
          popupRef.current.remove();
          popupRef.current = null;
        }
        if (onSegmentClickRef.current) {
          onSegmentClickRef.current({
            segment_id: props.segment_id,
            road_name: props.road_name,
            saturation_score: Number(props.saturation_score),
            avg_speed: Number(props.avg_speed),
            vehicle_count: Number(props.vehicle_count),
            level: props.level,
          });
        }
      });

      setMapLoaded(true);
      } catch (err) {
        console.error("[CityMap3D] Map load error:", err);
        setMapError("3D 地圖圖層初始化失敗，請重新整理後再試。");
        setMapLoaded(true); // 保留已成功建立的圖層，避免整個儀表板失效
      }
    });

    mapRef.current = map;

    return () => {
      map.off("error", handleMapError);
      if (popupRef.current) {
        popupRef.current.remove();
        popupRef.current = null;
      }
      if (mapRef.current === map) mapRef.current = null;
      try {
        map.remove();
      } catch (error) {
        // MapLibre may have no renderer to destroy when WebGL initialization fails.
        console.warn("[CityMap3D] Map cleanup skipped:", error);
      }
    };
  }, []);

  // 相機導播：地圖就緒後建立，卸載時解掉 DOM 監聽與動畫迴圈
  useEffect(() => {
    if (!mapLoaded || !mapRef.current) return;
    const director = createCameraDirector(mapRef.current, {
      onStateChange: setCameraState,
    });
    directorRef.current = director;
    return () => {
      director.dispose();
      directorRef.current = null;
    };
  }, [mapLoaded]);

  // 突發事件 → 飛到事件點並開始環繞。focusTarget.key 變化才算新事件，
  // 路網每次輪詢重新取回同一筆預警時不會把鏡頭一直拉回去。
  // mapLoaded 也列入依賴：預警比地圖載入更早到時，等導播建立好會補飛一次
  useEffect(() => {
    if (!directorRef.current || !focusTarget?.key) return;
    const center = resolveFocusCenter(focusTarget);
    if (!center) return;
    lastFocusRef.current = { ...focusTarget, center };
    directorRef.current.focus({ center, orbit: focusTarget.orbit !== false });
  }, [focusTarget?.key, mapLoaded]); // eslint-disable-line react-hooks/exhaustive-deps

  const refocus = () => {
    const target = lastFocusRef.current;
    if (!target || !directorRef.current) return;
    directorRef.current.focus({ center: target.center, orbit: true });
  };

  const autoDriving = cameraState === "flying" || cameraState === "orbiting";

  // 當 segments 資料更新時，更新道路圖層
  useEffect(() => {
    if (!mapLoaded || !mapRef.current) return;
    const map = mapRef.current;
    const source = map.getSource("traffic-roads");
    if (!source) return;

    const geojson = buildRoadGeoJSON(segments, selectedSegmentId);
    source.setData(geojson);
  }, [segments, selectedSegmentId, mapLoaded]);

  // 動態光點動畫：沿路段移動的小光點
  useEffect(() => {
    if (!mapLoaded || !mapRef.current || segments.length === 0) return;
    const map = mapRef.current;
    let animId;
    const DOTS_PER_ROAD = 3;

    const animate = () => {
      const now = performance.now();
      const dotSource = map.getSource("traffic-dots");
      if (!dotSource) { animId = requestAnimationFrame(animate); return; }

      const features = [];
      for (const seg of segments) {
        const fwdCoords = SEGMENT_COORDS_FWD[seg.segment_id];
        const revCoords = SEGMENT_COORDS_REV[seg.segment_id];
        if (!fwdCoords || fwdCoords.length < 2) continue;

        const speed = Math.max(seg.avg_speed || 20, 5) / 50;
        for (let d = 0; d < DOTS_PER_ROAD; d++) {
          // 正向點（用正向偏移座標）
          const tFwd = ((now * speed * 0.0001) + (d / DOTS_PER_ROAD)) % 1;
          const ptFwd = interpolateAlongLine(fwdCoords, tFwd);
          if (ptFwd) {
            features.push({ type: "Feature", geometry: { type: "Point", coordinates: ptFwd }, properties: {} });
          }
          // 反向點（用反向偏移座標）
          if (revCoords && revCoords.length >= 2) {
            const tRev = ((now * speed * 0.00008) + (d / DOTS_PER_ROAD) + 0.5) % 1;
            const ptRev = interpolateAlongLine(revCoords, tRev);
            if (ptRev) {
              features.push({ type: "Feature", geometry: { type: "Point", coordinates: ptRev }, properties: {} });
            }
          }
        }
      }

      dotSource.setData({ type: "FeatureCollection", features });
      animId = requestAnimationFrame(animate);
    };

    animId = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(animId);
  }, [segments, mapLoaded]);

  // 當 stations 資料更新時，更新站點圖層
  useEffect(() => {
    if (!mapLoaded || !mapRef.current) return;
    const map = mapRef.current;
    const source = map.getSource("stations");
    if (!source) return;

    const geojson = buildStationGeoJSON(
      stations,
      thresholds?.sop6_roaming ?? Number.POSITIVE_INFINITY,
    );
    source.setData(geojson);
  }, [stations, mapLoaded, thresholds]);

  return (
    <div className={`relative rounded-xl overflow-hidden border border-gray-200 shadow-sm ${className}`}>
      {/* 地圖容器：使用絕對定位填滿父容器高度 */}
      <div ref={mapContainer} style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0 }} />
      {mapError && (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-card p-6 text-center text-card-foreground">
          <div className="max-w-md rounded-lg border border-border bg-background p-4 shadow-sm">
            <div className="text-sm font-semibold">3D 地圖目前無法顯示</div>
            <p className="mt-2 text-sm text-muted-foreground">{mapError}</p>
            <p className="mt-2 text-xs text-muted-foreground">
              請在 Chrome 系統設定啟用圖形加速並重新啟動瀏覽器。
            </p>
          </div>
        </div>
      )}
      {/* 自動導播狀態：正在追蹤時告知可隨時接手，接手後留一個回到事件點的入口 */}
      {(autoDriving || cameraState === "released") && lastFocusRef.current && (
        <div
          className="absolute top-3 left-1/2 -translate-x-1/2 z-10 flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--card)]/92 px-3 py-1.5 shadow-sm backdrop-blur-sm"
          aria-live="polite"
        >
          {autoDriving ? (
            <>
              <Orbit className="w-3.5 h-3.5 shrink-0 text-[var(--status-error)] animate-spin [animation-duration:3s]" />
              <span className="text-xs font-medium">
                自動追蹤 {lastFocusRef.current.label || lastFocusRef.current.segmentId}
              </span>
              <span className="text-xs text-[var(--muted-foreground)]">· 操作地圖即接手</span>
              <button
                type="button"
                onClick={() => directorRef.current?.release("user")}
                className="ml-1 flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium text-[var(--muted-foreground)] transition hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)] focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
              >
                <Hand className="w-3 h-3" />
                接手
              </button>
            </>
          ) : (
            <>
              <Hand className="w-3.5 h-3.5 shrink-0 text-[var(--muted-foreground)]" />
              <span className="text-xs text-[var(--muted-foreground)]">已由您操控</span>
              <button
                type="button"
                onClick={refocus}
                className="ml-1 flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium text-[var(--foreground)] transition hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)] focus-visible:ring-[var(--ring)] focus-visible:ring-[3px]"
              >
                <Crosshair className="w-3 h-3" />
                重新聚焦{lastFocusRef.current.label || ""}
              </button>
            </>
          )}
        </div>
      )}

      {/* 圖例 */}
      <div className="absolute bottom-4 left-4 bg-white/90 backdrop-blur-sm rounded-lg px-3 py-2 shadow-md text-xs z-10">
        <div className="font-semibold text-gray-700 mb-1.5">路段飽和度</div>
        {/* 圖例色點直接取用線條顏色，調整彩度時不會和地圖脫鉤 */}
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full" style={{ background: levelColor("NORMAL") }} />正常</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full" style={{ background: levelColor("B") }} />壅擠</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full" style={{ background: levelColor("A") }} />癱瘓</span>
        </div>
      </div>
    </div>
  );
}
