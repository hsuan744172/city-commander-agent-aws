import { useEffect, useRef, useState } from "react";
import {
  LngLatBounds,
  Map as MaplibreMap,
  Marker,
  NavigationControl,
  Popup,
  setWorkerUrl,
} from "maplibre-gl";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "maplibre-gl/dist/maplibre-gl.css";
import { MAP_LINE_STYLE, CASING_COLOR, routeColor } from "../lib/mapLineStyle";
import { applyBasemapTone } from "../lib/basemapTone";
import { SEGMENT_COORDS, XINYI_CENTER, incidentPointFor } from "../lib/segmentGeometry";

// 與 CityMap3D 同一個理由：MapLibre 6 的預設 worker URL 依賴 import.meta.url，
// 經 Vite bundle 後會指向不存在的 /assets/maplibre-gl-worker.mjs。
// 明確交給 Vite 打包 worker，產出帶 content hash 的同源資產。
setWorkerUrl(maplibreWorkerUrl);

// 事故點標記維持內嵌 SVG。原本從 cdnjs 與 raw.githubusercontent.com 抓 PNG，
// Demo 現場只要對外網路不通或 GitHub raw 被擋，地圖標記就整個破圖。
// 內嵌 data URI 一併省掉外部請求，也不需要處理 bundler 的圖片路徑問題。
const INCIDENT_MARKER_SVG = `
<svg xmlns="http://www.w3.org/2000/svg" width="26" height="38" viewBox="0 0 26 38">
  <path d="M13 0C5.8 0 0 5.8 0 13c0 9.2 13 25 13 25s13-15.8 13-25C26 5.8 20.2 0 13 0z"
        fill="#DC2626" stroke="#ffffff" stroke-width="2"/>
  <circle cx="13" cy="13" r="4.5" fill="#ffffff"/>
</svg>`.trim();

const INCIDENT_MARKER_URL = `data:image/svg+xml;utf8,${encodeURIComponent(INCIDENT_MARKER_SVG)}`;

// 事故聚焦視圖的三種路線。顏色／寬度／透明度全部取自 lib/mapLineStyle，
// 與儀表板 3D 路網圖同一組設定；虛線間隔以線寬為單位（MapLibre 的 dasharray 語意）。
// 陣列順序 = 疊圖順序，事故路段畫在最上層。
const ROUTE_LAYERS = [
  { kind: "secondary", width: MAP_LINE_STYLE.width.secondary, dash: [2.5, 2.5] },
  { kind: "primary", width: MAP_LINE_STYLE.width.primary, dash: [3, 1.5] },
  { kind: "affected", width: MAP_LINE_STYLE.width.affected, dash: null },
];

const EMPTY_FC = { type: "FeatureCollection", features: [] };

const lineFeature = (coordinates) => ({
  type: "Feature",
  properties: {},
  geometry: { type: "LineString", coordinates },
});

/**
 * 由建議書算出三種路線的座標（[lng, lat] 折線）與事故點座標。
 */
function buildRouteGeometry(advisory) {
  const eid = advisory?.event_identification || {};
  const primary = advisory?.route_advisory?.primary_evacuation_route;
  const affectedSeg = eid.affected_segment || "";

  const affected = SEGMENT_COORDS[affectedSeg] ? [SEGMENT_COORDS[affectedSeg]] : [];
  const primaryId = primary?.primary_route_id;
  const primaryLines = primaryId && SEGMENT_COORDS[primaryId] ? [SEGMENT_COORDS[primaryId]] : [];
  const secondary = (primary?.secondary_routes || [])
    .map((route) => SEGMENT_COORDS[route?.segment_id])
    .filter(Boolean);

  return {
    lines: { affected, primary: primaryLines, secondary },
    incidentPoint: incidentPointFor(affectedSeg),
    label: eid.location || affectedSeg || "事故位置",
  };
}

/**
 * IncidentMap — 事件注入頁的事故聚焦圖（MapLibre GL JS）
 * - 與儀表板 CityMap3D 共用 OpenFreeMap 向量圖磚、底圖降彩與線條樣式
 * - 平面視角（pitch 0）、無 3D 建築：焦點是事故路段與疏散路徑
 * - advisory 更新時重算圖層並把事故＋疏散路徑一起框進畫面
 */
export default function IncidentMap({ advisory }) {
  const mapContainer = useRef(null);
  const mapRef = useRef(null);
  const markerRef = useRef(null);
  const [mapLoaded, setMapLoaded] = useState(false);
  const [mapError, setMapError] = useState("");

  // 初始化地圖（只做一次；advisory 變更走下面的資料更新 effect）
  useEffect(() => {
    if (mapRef.current || !mapContainer.current) return;

    const probeCanvas = document.createElement("canvas");
    if (!probeCanvas.getContext("webgl2")) {
      setMapError("Chrome 目前無法使用 WebGL 2，疏散路線圖已暫停顯示。");
      return;
    }

    let map;
    try {
      map = new MaplibreMap({
        container: mapContainer.current,
        style: "https://tiles.openfreemap.org/styles/bright",
        center: XINYI_CENTER,
        zoom: 14.5,
        pitch: 0,
        canvasContextAttributes: { antialias: true },
      });
      mapRef.current = map;
      setMapError("");
    } catch (error) {
      console.error("[IncidentMap] Map initialization error:", error);
      setMapError("疏散路線圖初始化失敗，建議書內容仍可正常閱讀。");
      return;
    }

    let didLoad = false;
    const handleMapError = (event) => {
      const message = String(event?.error?.message || event?.error || "未知錯誤");
      console.error("[IncidentMap] MapLibre error:", message, event?.error || event);

      // 單一圖磚的暫時失敗也會發出 error；地圖已載入後不該因此整片遮住。
      // Worker、style 與首次載入錯誤才是致命的，必須明確呈現。
      if (
        !didLoad ||
        /worker|dynamically imported|style.*load|failed to fetch/i.test(message)
      ) {
        setMapError("疏散路線圖資源載入失敗，請重新整理；若問題持續，請聯絡系統管理員。");
      }
    };

    map.on("error", handleMapError);
    map.addControl(new NavigationControl(), "top-right");

    map.on("load", () => {
      didLoad = true;
      setMapError("");
      try {
        // 底圖降彩必須在加入自訂圖層之前，否則疏散路線的紅／綠／藍也會被一起洗掉。
        applyBasemapTone(map);

        // 隱藏底圖 symbol 圖層（POI、路名、門牌），畫面只留疏散路線與事故點。
        try {
          for (const layer of map.getStyle().layers || []) {
            if (layer.type === "symbol") {
              map.setLayoutProperty(layer.id, "visibility", "none");
            }
          }
        } catch (error) {
          console.warn("[IncidentMap] hiding basemap symbols failed:", error);
        }

        for (const { kind, width, dash } of ROUTE_LAYERS) {
          map.addSource(`route-${kind}`, { type: "geojson", data: EMPTY_FC });

          // casing：深色底線，讓路線在降彩底圖上仍有清楚邊界（同 CityMap3D 作法）
          map.addLayer({
            id: `route-${kind}-casing`,
            type: "line",
            source: `route-${kind}`,
            paint: {
              "line-color": CASING_COLOR,
              "line-width": width + 4,
              "line-opacity": MAP_LINE_STYLE.opacity.casing,
            },
            layout: { "line-cap": "round", "line-join": "round" },
          });

          map.addLayer({
            id: `route-${kind}-line`,
            type: "line",
            source: `route-${kind}`,
            paint: {
              "line-color": routeColor(kind),
              "line-width": width,
              "line-opacity": MAP_LINE_STYLE.opacity[kind],
              ...(dash ? { "line-dasharray": dash } : {}),
            },
            layout: { "line-cap": dash ? "butt" : "round", "line-join": "round" },
          });
        }

        setMapLoaded(true);
      } catch (error) {
        console.error("[IncidentMap] Map load error:", error);
        setMapError("疏散路線圖層初始化失敗，請重新整理後再試。");
      }
    });

    return () => {
      map.off("error", handleMapError);
      if (markerRef.current) {
        markerRef.current.remove();
        markerRef.current = null;
      }
      if (mapRef.current === map) mapRef.current = null;
      setMapLoaded(false);
      try {
        map.remove();
      } catch (error) {
        // WebGL 初始化失敗時 MapLibre 沒有 renderer 可銷毀，忽略即可。
        console.warn("[IncidentMap] Map cleanup skipped:", error);
      }
    };
  }, []);

  // advisory 變更：重算圖層資料、移動事故標記、把事故與疏散路徑框進畫面
  useEffect(() => {
    if (!mapLoaded || !mapRef.current) return;
    const map = mapRef.current;

    const clearMarker = () => {
      if (markerRef.current) {
        markerRef.current.remove();
        markerRef.current = null;
      }
    };

    // 沒有建議書（或建議書失敗）時只留乾淨底圖，視角回到信義計畫區中心
    if (!advisory || advisory.error) {
      for (const { kind } of ROUTE_LAYERS) {
        map.getSource(`route-${kind}`)?.setData(EMPTY_FC);
      }
      clearMarker();
      map.easeTo({ center: XINYI_CENTER, zoom: 14.5, duration: 400 });
      return;
    }

    const { lines, incidentPoint, label } = buildRouteGeometry(advisory);

    for (const { kind } of ROUTE_LAYERS) {
      map.getSource(`route-${kind}`)?.setData({
        type: "FeatureCollection",
        features: lines[kind].map(lineFeature),
      });
    }

    // 事故點標記：沿用內嵌 SVG，點擊顯示地點名稱
    const popupContent = document.createElement("strong");
    popupContent.textContent = label;
    // offset 需大於標記高度（38px），否則氣泡會蓋住圖釘
    const popup = new Popup({ offset: 40, closeButton: false }).setDOMContent(popupContent);

    if (markerRef.current) {
      markerRef.current.setLngLat(incidentPoint).setPopup(popup);
    } else {
      const element = document.createElement("img");
      element.src = INCIDENT_MARKER_URL;
      element.width = 26;
      element.height = 38;
      element.alt = "事故位置標記";
      element.draggable = false;
      element.style.display = "block";
      element.style.cursor = "pointer";
      markerRef.current = new Marker({ element, anchor: "bottom" })
        .setLngLat(incidentPoint)
        .setPopup(popup)
        .addTo(map);
    }

    // 事故路段 + 主／次疏散路徑一起入框；只有事故點時退回定點縮放
    const bounds = new LngLatBounds();
    let hasLine = false;
    for (const { kind } of ROUTE_LAYERS) {
      for (const coords of lines[kind]) {
        for (const coord of coords) {
          bounds.extend(coord);
          hasLine = true;
        }
      }
    }

    if (hasLine) {
      bounds.extend(incidentPoint);
      map.fitBounds(bounds, { padding: 56, maxZoom: 16, duration: 600 });
    } else {
      map.easeTo({ center: incidentPoint, zoom: 16, duration: 600 });
    }
  }, [advisory, mapLoaded]);

  return (
    <div className="relative h-full rounded-lg overflow-hidden border border-[var(--border)]">
      <div ref={mapContainer} style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0 }} />
      {mapError && (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-[var(--card)] p-4 text-center">
          <div className="max-w-sm rounded-lg border border-[var(--border)] bg-[var(--background)] p-3 shadow-sm">
            <div className="text-sm font-semibold">疏散路線圖目前無法顯示</div>
            <p className="mt-2 text-sm text-[var(--muted-foreground)]">{mapError}</p>
          </div>
        </div>
      )}
    </div>
  );
}
