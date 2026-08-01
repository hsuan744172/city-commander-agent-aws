import { useEffect, useRef, useState } from "react";
import { Map as MaplibreMap, NavigationControl, Popup } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

// ============================================================
// 信義計畫區路段座標 (lng, lat) — 來源：OpenStreetMap Overpass API
// 資料授權：© OpenStreetMap contributors, ODbL 1.0
// ============================================================
const SEGMENT_COORDS = {
  // 忠孝東路四段：東西向，從敦化南路到基隆路 (way 255431333 eastbound)
  RD_TPE_001: [[121.5491111,25.0414462],[121.5496454,25.0414311],[121.5507018,25.0414053],[121.5518126,25.0413908],[121.5528894,25.0413710],[121.5540858,25.0413490],[121.5544492,25.0413423],[121.5547873,25.0413361],[121.5555718,25.0414465],[121.5561215,25.0414375],[121.5576145,25.0412833],[121.5577382,25.0412799],[121.5593809,25.0412216],[121.5610007,25.0411741],[121.5615828,25.0411600]],
  // 光復南路：南北向 (northbound way 746296430 + 506339442)
  RD_TPE_002: [[121.5575276,25.0378611],[121.5575731,25.0393422],[121.5576145,25.0412833],[121.5576181,25.0414157],[121.5576241,25.0417443],[121.5576423,25.0425264],[121.5576573,25.0431115],[121.5576632,25.0435239],[121.5576693,25.0439487],[121.5576844,25.0449905]],
  // 基隆路一段：南北向偏斜 (northbound)
  RD_TPE_003: [[121.5605277,25.0343462],[121.5615056,25.0359423],[121.5635643,25.0395598],[121.5645790,25.0411035],[121.5654947,25.0426500],[121.5660201,25.0435592],[121.5671405,25.0454300],[121.5680022,25.0468180]],
  // 市民大道四段：東西向 (eastbound)
  RD_TPE_004: [[121.5439383,25.0449789],[121.5464396,25.0450046],[121.5486443,25.0447762],[121.5508101,25.0445426],[121.5522774,25.0443109],[121.5542600,25.0443028],[121.5556360,25.0445740],[121.5576844,25.0449905]],
  // 仁愛路四段：東西向 (eastbound)
  RD_TPE_005: [[121.5437600,25.0379096],[121.5460393,25.0378690],[121.5479435,25.0379694],[121.5497128,25.0380301],[121.5529366,25.0378378],[121.5554302,25.0377944],[121.5575276,25.0378611],[121.5606536,25.0377084],[121.5619400,25.0373552]],
  // 敦化南路一段：南北向 (northbound)
  RD_TPE_006: [[121.5485749,25.0364206],[121.5486039,25.0373434],[121.5486002,25.0389471],[121.5486159,25.0414665],[121.5486299,25.0426119],[121.5486443,25.0447762],[121.5486457,25.0449924]],
  // 松高路：東西向 (eastbound)
  RD_TPE_007: [[121.5615402,25.0391995],[121.5636125,25.0391447],[121.5650897,25.0391155],[121.5660984,25.0391181],[121.5676428,25.0390906],[121.5685218,25.0390749]],
  // 延吉街：南北向偏斜
  RD_TPE_008: [[121.5544785,25.0414800],[121.5541723,25.0426146],[121.5537795,25.0445125],[121.5535232,25.0466363],[121.5533420,25.0481763]],
  // 基隆路地下道（近基隆路一段北段）
  RD_TPE_009: [[121.5671405,25.0454300],[121.5673934,25.0458103],[121.5680022,25.0468180],[121.5687763,25.0481134]],
  // 市府路：南北向
  RD_TPE_010: [[121.5635362,25.0330043],[121.5635561,25.0340152],[121.5635978,25.0357732],[121.5635646,25.0358947],[121.5635734,25.0372648],[121.5636088,25.0390162],[121.5636125,25.0391447]],
  // 松壽路：東西向
  RD_TPE_011: [[121.5611968,25.0359480],[121.5619558,25.0359342],[121.5635646,25.0358947],[121.5650045,25.0358787],[121.5663989,25.0358534],[121.5675710,25.0358321],[121.5684456,25.0358278]],
  // 敦化南路二段：南北向（一段延伸往南）
  RD_TPE_012: [[121.5485555,25.0333661],[121.5485749,25.0364206]],
  // 信義路五段：東西向
  RD_TPE_013: [[121.5597077,25.0331059],[121.5606004,25.0330712],[121.5613824,25.0330508],[121.5623292,25.0330300],[121.5634121,25.0330053],[121.5652661,25.0329623],[121.5654166,25.0329580]],
  // 松智路：南北向
  RD_TPE_014: [[121.5654166,25.0329580],[121.5654326,25.0339542],[121.5654485,25.0357440],[121.5654537,25.0360001],[121.5654874,25.0370553],[121.5655044,25.0378973],[121.5655264,25.0389904]],
  // 復興南路一段：南北向
  RD_TPE_015: [[121.5437213,25.0356214],[121.5437448,25.0368158],[121.5437575,25.0377844],[121.5438051,25.0398860],[121.5438379,25.0415558],[121.5438661,25.0425198],[121.5439352,25.0447557]],
};

// ============================================================
// 人流密度觀測站座標 [lng, lat] — 來源：OSM Nominatim API
// 資料授權：© OpenStreetMap contributors, ODbL 1.0
// ============================================================
const STATION_COORDS = {
  BS_TPE_DOME:   [121.5595809, 25.0424051],  // 大巨蛋場館
  BS_MRT_BL17:   [121.5574500, 25.0412200],  // 捷運國父紀念館站
  BS_SS_PARK:    [121.5607970, 25.0437228],  // 松山文創園區
  BS_MRT_BL16:   [121.5505994, 25.0414809],  // 捷運忠孝敦化站
  BS_XY_VIESHOW: [121.5672427, 25.0351570],  // 信義威秀商圈
  BS_TPE_101:    [121.5644995, 25.0338352],  // 台北101廣場
  BS_BUS_TERM:   [121.5651415, 25.0405413],  // 市府轉運站
  BS_XY_ATT:     [121.5662040, 25.0356567],  // ATT4FUN周邊
  BS_PARK_ZS:    [121.5596096, 25.0394803],  // 中山公園
};

const STATION_NAMES = {
  BS_TPE_DOME:   "大巨蛋場館",
  BS_MRT_BL17:   "國父紀念館站",
  BS_SS_PARK:    "松山文創園區",
  BS_MRT_BL16:   "忠孝敦化站",
  BS_XY_VIESHOW: "信義威秀商圈",
  BS_TPE_101:    "台北101廣場",
  BS_BUS_TERM:   "市府轉運站",
  BS_XY_ATT:     "ATT4FUN周邊",
  BS_PARK_ZS:    "中山公園",
};

/**
 * 建立站點 GeoJSON — 結合靜態座標與動態人流資料
 */
function buildStationGeoJSON(stations = []) {
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
        roaming_user_pct: data?.roaming_user_pct ?? 0,
        stay_time_avg: data?.stay_time_avg ?? 0,
        has_roaming_alert: (data?.roaming_user_pct ?? 0) >= 30 ? 1 : 0,
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
 * 飽和度 → 顏色（與即時路網監測一致）
 * A 級 (≥ 0.95): 紅色 --status-error
 * B 級 (≥ 0.85): 橘黃 --status-warning
 * Normal (< 0.85): 綠色 --status-success
 */
function saturationToColor(score) {
  if (score >= 0.95) return "#D94F4F";
  if (score >= 0.85) return "#C8922A";
  return "#3A9E74";
}

/**
 * 將後端 segments 資料轉換為 GeoJSON FeatureCollection
 */
function buildRoadGeoJSON(segments, selectedId = null) {
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
        selected: seg.segment_id === selectedId ? 1 : 0,
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
export default function CityMap3D({
  segments = [],
  stations = [],
  selectedSegmentId = null,
  onSegmentClick,
  className = "",
}) {
  const mapContainer = useRef(null);
  const mapRef = useRef(null);
  const popupRef = useRef(null);
  const [mapLoaded, setMapLoaded] = useState(false);
  const onSegmentClickRef = useRef(onSegmentClick);
  onSegmentClickRef.current = onSegmentClick;

  // 初始化地圖
  useEffect(() => {
    if (mapRef.current || !mapContainer.current) return;

    const map = new MaplibreMap({
      container: mapContainer.current,
      style: "https://tiles.openfreemap.org/styles/bright",
      center: [121.5580, 25.0400], // 信義計畫區中心
      zoom: 14.5,
      pitch: 50,
      bearing: -17.6,
      canvasContextAttributes: { antialias: true },
    });

    map.addControl(new NavigationControl(), "top-right");

    map.on("load", () => {
      try {
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
            "fill-extrusion-base": ["get", "render_min_height"],
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

      // 隱形寬線：用於擴大點擊/hover 的命中區域
      map.addLayer({
        id: "traffic-roads-hitarea",
        type: "line",
        source: "traffic-roads",
        paint: {
          "line-color": "#000000",
          "line-opacity": 0.01,
          "line-width": 28,
        },
        layout: {
          "line-cap": "round",
          "line-join": "round",
        },
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

      // 單選路段的額外粗外框（紫色不與飽和度色階衝突）
      map.addLayer({
        id: "traffic-roads-selected-outline",
        type: "line",
        source: "traffic-roads",
        filter: ["==", ["get", "selected"], 1],
        paint: {
          "line-color": "#BA56DE",
          "line-width": [
            "interpolate", ["linear"], ["zoom"],
            13, 10,
            16, 18,
            18, 28,
          ],
          "line-blur": 2,
          "line-opacity": 0.5,
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
          ? '<div style="color:#f59e0b;font-weight:bold;margin-top:4px">🌐 漫遊率 ≥ 30% — 需多語通報</div>'
          : "";
        const rateLabel = props.growth_rate > 0 ? `+${props.growth_rate}` : `${props.growth_rate}`;
        const html = `
          <div style="font-family:sans-serif;font-size:13px;line-height:1.6;min-width:160px">
            <strong style="font-size:14px">${props.name}</strong>
            <div style="margin-top:4px">人流：<b>${Number(props.user_count).toLocaleString()}</b> 人</div>
            <div>增長率：<b>${rateLabel}</b></div>
            <div>漫遊率：${props.roaming_user_pct}%</div>
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
        const levelLabel = props.level === "A" ? "🔴 A 級癱瘓" : props.level === "B" ? "🟡 B 級壅擠" : "🟢 正常";

        const html = `
          <div style="font-family:sans-serif;font-size:13px;line-height:1.6;min-width:160px">
            <strong style="font-size:14px">${props.road_name}</strong>
            <div style="margin-top:4px">${levelLabel}</div>
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
        setMapLoaded(true); // still try to load data
      }
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

    const geojson = buildRoadGeoJSON(segments, selectedSegmentId);
    source.setData(geojson);
  }, [segments, selectedSegmentId, mapLoaded]);

  // 當 stations 資料更新時，更新站點圖層
  useEffect(() => {
    if (!mapLoaded || !mapRef.current) return;
    const map = mapRef.current;
    const source = map.getSource("stations");
    if (!source) return;

    const geojson = buildStationGeoJSON(stations);
    source.setData(geojson);
  }, [stations, mapLoaded]);

  return (
    <div className={`relative rounded-xl overflow-hidden border border-gray-200 shadow-sm ${className}`}>
      {/* 地圖容器：使用絕對定位填滿父容器高度 */}
      <div ref={mapContainer} style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0 }} />
      {/* 圖例 */}
      <div className="absolute bottom-4 left-4 bg-white/90 backdrop-blur-sm rounded-lg px-3 py-2 shadow-md text-xs z-10">
        <div className="font-semibold text-gray-700 mb-1.5">路段飽和度</div>
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full" style={{ background: "#3A9E74" }} />正常</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full" style={{ background: "#C8922A" }} />壅擠</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full" style={{ background: "#D94F4F" }} />癱瘓</span>
        </div>
      </div>
    </div>
  );
}
