import { useEffect, useRef, useState } from "react";
import { Map, NavigationControl, Popup } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

// ============================================================
// 信義計畫區路段座標 (lng, lat) — GeoJSON 格式 [經度, 緯度]
// 來源：IncidentMap.jsx 的 Leaflet [lat, lng] 轉換
// ============================================================
const SEGMENT_COORDS = {
  RD_TPE_001: [[121.5513,25.04165],[121.5521,25.04163],[121.5533,25.04161],[121.5545,25.04160],[121.5557,25.04158],[121.5568,25.04157],[121.5577,25.04155],[121.5590,25.04153],[121.5602,25.04152],[121.5610,25.04150]],
  RD_TPE_002: [[121.5577,25.04490],[121.5577,25.04420],[121.5577,25.04350],[121.5577,25.04280],[121.5577,25.04165],[121.5577,25.04080],[121.5577,25.03990],[121.5577,25.03900],[121.5577,25.03850]],
  RD_TPE_003: [[121.5610,25.04320],[121.5610,25.04230],[121.5610,25.04150],[121.5610,25.04050],[121.5610,25.03950],[121.5611,25.03850],[121.5611,25.03750],[121.5611,25.03650],[121.5611,25.03550]],
  RD_TPE_004: [[121.5435,25.04490],[121.5450,25.04490],[121.5470,25.04490],[121.5492,25.04490],[121.5513,25.04490],[121.5535,25.04490],[121.5557,25.04490],[121.5577,25.04490]],
  RD_TPE_005: [[121.5492,25.03850],[121.5510,25.03850],[121.5530,25.03850],[121.5550,25.03850],[121.5568,25.03850],[121.5577,25.03850],[121.5595,25.03850],[121.5610,25.03850],[121.5635,25.03850]],
  RD_TPE_006: [[121.5492,25.04490],[121.5492,25.04380],[121.5492,25.04280],[121.5492,25.04165],[121.5492,25.04050],[121.5492,25.03950],[121.5492,25.03850]],
  RD_TPE_007: [[121.5611,25.03650],[121.5625,25.03650],[121.5640,25.03650],[121.5655,25.03650],[121.5670,25.03650],[121.5685,25.03650]],
  RD_TPE_008: [[121.5521,25.04300],[121.5521,25.04165],[121.5521,25.04050],[121.5521,25.03950],[121.5521,25.03850]],
  RD_TPE_009: [[121.5610,25.04490],[121.5610,25.04420],[121.5610,25.04350],[121.5610,25.04320]],
  RD_TPE_010: [[121.5635,25.03850],[121.5635,25.03750],[121.5635,25.03650],[121.5635,25.03550],[121.5635,25.03450],[121.5635,25.03350]],
  RD_TPE_011: [[121.5611,25.03480],[121.5625,25.03480],[121.5640,25.03480],[121.5655,25.03480],[121.5670,25.03480],[121.5685,25.03480]],
  RD_TPE_012: [[121.5492,25.03850],[121.5492,25.03750],[121.5492,25.03650],[121.5492,25.03550],[121.5492,25.03450]],
  RD_TPE_013: [[121.5611,25.03350],[121.5625,25.03350],[121.5640,25.03350],[121.5655,25.03350],[121.5670,25.03350],[121.5685,25.03350]],
  RD_TPE_014: [[121.5685,25.03650],[121.5685,25.03550],[121.5685,25.03480],[121.5685,25.03400],[121.5685,25.03350]],
  RD_TPE_015: [[121.5435,25.04490],[121.5435,25.04400],[121.5435,25.04300],[121.5435,25.04200],[121.5435,25.04165]],
};

/**
 * 飽和度 → 顏色漸變
 * 0.0~0.5: 綠色 (暢通)
 * 0.5~0.7: 黃色 (略擁擠)
 * 0.7~0.85: 橘色 (壅擠)
 * 0.85~1.0: 紅色 (癱瘓)
 */
function saturationToColor(score) {
  if (score <= 0.5) {
    const t = score / 0.5;
    const r = Math.round(34 + t * (180 - 34));
    const g = Math.round(197 + t * (200 - 197));
    const b = Math.round(94 - t * 60);
    return `rgb(${r},${g},${b})`;
  } else if (score <= 0.7) {
    const t = (score - 0.5) / 0.2;
    const r = Math.round(180 + t * (245 - 180));
    const g = Math.round(200 - t * (200 - 158));
    const b = Math.round(34 - t * 23);
    return `rgb(${r},${g},${b})`;
  } else if (score <= 0.85) {
    const t = (score - 0.7) / 0.15;
    const r = Math.round(245 + t * (234 - 245));
    const g = Math.round(158 - t * (158 - 67));
    const b = Math.round(11 + t * (53 - 11));
    return `rgb(${r},${g},${b})`;
  } else {
    const t = Math.min((score - 0.85) / 0.15, 1);
    const r = Math.round(234 - t * (234 - 185));
    const g = Math.round(67 - t * (67 - 28));
    const b = Math.round(53 - t * (53 - 28));
    return `rgb(${r},${g},${b})`;
  }
}

/**
 * 將後端 segments 資料轉換為 GeoJSON FeatureCollection
 */
function buildRoadGeoJSON(segments) {
  const features = [];
  for (const seg of segments) {
    const coords = SEGMENT_COORDS[seg.segment_id];
    if (!coords) continue;
    features.push({
      type: "Feature",
      properties: {
        segment_id: seg.segment_id,
        road_name: seg.road_name,
        saturation_score: seg.saturation_score,
        avg_speed: seg.avg_speed,
        vehicle_count: seg.vehicle_count,
        level: seg.level,
        lane_status: seg.lane_status,
        color: saturationToColor(seg.saturation_score),
      },
      geometry: {
        type: "LineString",
        coordinates: coords,
      },
    });
  }
  return { type: "FeatureCollection", features };
}

/**
 * CityMap3D — 使用 MapLibre GL JS 建立 3D 城市地圖
 * - OpenFreeMap 向量圖磚 + 3D 建築
 * - 道路線依飽和度即時漸變色
 * - 串接後端 /api/status 自動刷新
 */
export default function CityMap3D({ segments = [], className = "" }) {
  const mapContainer = useRef(null);
  const mapRef = useRef(null);
  const popupRef = useRef(null);
  const [mapLoaded, setMapLoaded] = useState(false);

  // 初始化地圖
  useEffect(() => {
    if (mapRef.current || !mapContainer.current) return;

    const map = new Map({
      container: mapContainer.current,
      style: "https://tiles.openfreemap.org/styles/bright",
      center: [121.5577, 25.0390], // 信義計畫區中心
      zoom: 15.2,
      pitch: 50,
      bearing: -17.6,
      canvasContextAttributes: { antialias: true },
    });

    map.addControl(new NavigationControl(), "top-right");

    map.on("load", () => {
      // --- 3D 建築圖層 ---
      const layers = map.getStyle().layers;
      let labelLayerId;
      for (let i = 0; i < layers.length; i++) {
        if (layers[i].type === "symbol" && layers[i].layout?.["text-field"]) {
          labelLayerId = layers[i].id;
          break;
        }
      }

      map.addSource("openfreemap", {
        url: "https://tiles.openfreemap.org/planet",
        type: "vector",
      });

      map.addLayer(
        {
          id: "3d-buildings",
          source: "openfreemap",
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
            "fill-extrusion-base": [
              "case",
              [">=", ["get", "zoom"], 16],
              ["get", "render_min_height"],
              0,
            ],
            "fill-extrusion-opacity": 0.75,
          },
        },
        labelLayerId
      );

      // --- 路網資料源與圖層 ---
      map.addSource("traffic-roads", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });

      // 路線外框（深色邊框增加深度感）
      map.addLayer({
        id: "traffic-roads-outline",
        type: "line",
        source: "traffic-roads",
        paint: {
          "line-color": "rgba(0,0,0,0.4)",
          "line-width": [
            "interpolate", ["linear"], ["zoom"],
            13, 5,
            16, 12,
            18, 20,
          ],
          "line-blur": 1,
        },
        layout: {
          "line-cap": "round",
          "line-join": "round",
        },
      });

      // 路線主體（顏色依飽和度）
      map.addLayer({
        id: "traffic-roads-fill",
        type: "line",
        source: "traffic-roads",
        paint: {
          "line-color": ["get", "color"],
          "line-width": [
            "interpolate", ["linear"], ["zoom"],
            13, 3,
            16, 8,
            18, 15,
          ],
          "line-blur": 0,
        },
        layout: {
          "line-cap": "round",
          "line-join": "round",
        },
      });

      // --- 路段標籤 ---
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

      // --- Popup 互動 ---
      map.on("mouseenter", "traffic-roads-fill", () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "traffic-roads-fill", () => {
        map.getCanvas().style.cursor = "";
        if (popupRef.current) {
          popupRef.current.remove();
          popupRef.current = null;
        }
      });
      map.on("mousemove", "traffic-roads-fill", (e) => {
        if (!e.features?.length) return;
        const props = e.features[0].properties;
        const score = Math.round(props.saturation_score * 100);
        const levelLabel = props.level === "A" ? "🔴 A 級癱瘓" : props.level === "B" ? "🟡 B 級壅擠" : "🟢 正常";

        const html = `
          <div style="font-family:sans-serif;font-size:13px;line-height:1.6;min-width:160px">
            <strong style="font-size:14px">${props.road_name}</strong>
            <div style="margin-top:4px">${levelLabel}</div>
            <div>飽和度：<b>${score}%</b></div>
            <div>平均時速：${props.avg_speed} km/h</div>
            <div>車流量：${props.vehicle_count} 輛</div>
            <div style="color:#666;font-size:11px;margin-top:4px">${props.lane_status}</div>
          </div>
        `;

        if (popupRef.current) {
          popupRef.current.setLngLat(e.lngLat).setHTML(html);
        } else {
          popupRef.current = new Popup({
            closeButton: false,
            closeOnClick: false,
            offset: 10,
          })
            .setLngLat(e.lngLat)
            .setHTML(html)
            .addTo(map);
        }
      });

      setMapLoaded(true);
    });

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // 當 segments 資料更新時，更新道路圖層
  useEffect(() => {
    if (!mapLoaded || !mapRef.current) return;
    const map = mapRef.current;
    const source = map.getSource("traffic-roads");
    if (!source) return;

    const geojson = buildRoadGeoJSON(segments);
    source.setData(geojson);
  }, [segments, mapLoaded]);

  return (
    <div className={`relative rounded-xl overflow-hidden border border-gray-200 shadow-sm ${className}`}>
      {/* 地圖容器：使用絕對定位填滿父容器高度 */}
      <div ref={mapContainer} style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0 }} />
      {/* 圖例 */}
      <div className="absolute bottom-4 left-4 bg-white/90 backdrop-blur-sm rounded-lg px-3 py-2 shadow-md text-xs z-10">
        <div className="font-semibold text-gray-700 mb-1.5">路段飽和度</div>
        <div className="flex items-center gap-1">
          <div className="w-20 h-3 rounded-sm" style={{
            background: "linear-gradient(to right, #22c55e, #b4cc22, #f59e0b, #ea4335, #b91c1c)"
          }} />
        </div>
        <div className="flex justify-between text-[10px] text-gray-500 mt-0.5">
          <span>0%</span>
          <span>50%</span>
          <span>100%</span>
        </div>
      </div>
    </div>
  );
}
