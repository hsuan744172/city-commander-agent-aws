import { useEffect } from "react";
import { MapContainer, TileLayer, Marker, Polyline, Popup, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import L from "leaflet";

// ============================================================
// 信義計畫區路段多點座標 (沿街道節點，確保貼合道路)
// ============================================================
const SEGMENT_COORDS = {
  RD_TPE_001: [[25.04165,121.5513],[25.04163,121.5521],[25.04161,121.5533],[25.04160,121.5545],[25.04158,121.5557],[25.04157,121.5568],[25.04155,121.5577],[25.04153,121.5590],[25.04152,121.5602],[25.04150,121.5610]],
  RD_TPE_002: [[25.04490,121.5577],[25.04420,121.5577],[25.04350,121.5577],[25.04280,121.5577],[25.04165,121.5577],[25.04080,121.5577],[25.03990,121.5577],[25.03900,121.5577],[25.03850,121.5577]],
  RD_TPE_003: [[25.04320,121.5610],[25.04230,121.5610],[25.04150,121.5610],[25.04050,121.5610],[25.03950,121.5610],[25.03850,121.5611],[25.03750,121.5611],[25.03650,121.5611],[25.03550,121.5611]],
  RD_TPE_004: [[25.04490,121.5435],[25.04490,121.5450],[25.04490,121.5470],[25.04490,121.5492],[25.04490,121.5513],[25.04490,121.5535],[25.04490,121.5557],[25.04490,121.5577]],
  RD_TPE_005: [[25.03850,121.5492],[25.03850,121.5510],[25.03850,121.5530],[25.03850,121.5550],[25.03850,121.5568],[25.03850,121.5577],[25.03850,121.5595],[25.03850,121.5610],[25.03850,121.5635]],
  RD_TPE_006: [[25.04490,121.5492],[25.04380,121.5492],[25.04280,121.5492],[25.04165,121.5492],[25.04050,121.5492],[25.03950,121.5492],[25.03850,121.5492]],
  RD_TPE_007: [[25.03650,121.5611],[25.03650,121.5625],[25.03650,121.5640],[25.03650,121.5655],[25.03650,121.5670],[25.03650,121.5685]],
  RD_TPE_008: [[25.04300,121.5521],[25.04165,121.5521],[25.04050,121.5521],[25.03950,121.5521],[25.03850,121.5521]],
  RD_TPE_009: [[25.04490,121.5610],[25.04420,121.5610],[25.04350,121.5610],[25.04320,121.5610]],
  RD_TPE_010: [[25.03850,121.5635],[25.03750,121.5635],[25.03650,121.5635],[25.03550,121.5635],[25.03450,121.5635],[25.03350,121.5635]],
  RD_TPE_011: [[25.03480,121.5611],[25.03480,121.5625],[25.03480,121.5640],[25.03480,121.5655],[25.03480,121.5670],[25.03480,121.5685]],
  RD_TPE_012: [[25.03850,121.5492],[25.03750,121.5492],[25.03650,121.5492],[25.03550,121.5492],[25.03450,121.5492]],
  RD_TPE_013: [[25.03350,121.5611],[25.03350,121.5625],[25.03350,121.5640],[25.03350,121.5655],[25.03350,121.5670],[25.03350,121.5685]],
  RD_TPE_014: [[25.03650,121.5685],[25.03550,121.5685],[25.03480,121.5685],[25.03400,121.5685],[25.03350,121.5685]],
  RD_TPE_015: [[25.04490,121.5435],[25.04400,121.5435],[25.04300,121.5435],[25.04200,121.5435],[25.04165,121.5435]],
};

const INCIDENT_COORDS = {
  RD_TPE_001: [25.04160, 121.55570],
  RD_TPE_002: [25.04165, 121.55770],
  RD_TPE_003: [25.03950, 121.56100],
  RD_TPE_004: [25.04490, 121.55350],
  RD_TPE_005: [25.03850, 121.55500],
  RD_TPE_006: [25.04165, 121.54920],
  RD_TPE_007: [25.03650, 121.56550],
  RD_TPE_008: [25.04050, 121.55210],
  BS_MRT_BL17: [25.04100, 121.55750],
  BS_MRT_BL18: [25.03500, 121.56400],
};

// 事故點標記改用內嵌 SVG。原本從 cdnjs 與 raw.githubusercontent.com 抓 PNG，
// Demo 現場只要對外網路不通或 GitHub raw 被擋，地圖標記就整個破圖。
// 內嵌 data URI 一併省掉三個外部請求，也不需要處理 Leaflet 的 bundler 圖片路徑問題。
const INCIDENT_MARKER_SVG = `
<svg xmlns="http://www.w3.org/2000/svg" width="26" height="38" viewBox="0 0 26 38">
  <path d="M13 0C5.8 0 0 5.8 0 13c0 9.2 13 25 13 25s13-15.8 13-25C26 5.8 20.2 0 13 0z"
        fill="#DC2626" stroke="#ffffff" stroke-width="2"/>
  <circle cx="13" cy="13" r="4.5" fill="#ffffff"/>
</svg>`.trim();

const incidentIcon = new L.Icon({
  iconUrl: `data:image/svg+xml;utf8,${encodeURIComponent(INCIDENT_MARKER_SVG)}`,
  iconSize: [26, 38],
  iconAnchor: [13, 38],
  popupAnchor: [0, -32],
});

function FlyTo({ center }) {
  const map = useMap();
  useEffect(() => {
    if (center) map.flyTo(center, 16, { duration: 0.6 });
  }, [center, map]);
  return null;
}

export default function IncidentMap({ advisory }) {
  const center = [25.0390, 121.5580];

  if (!advisory || advisory.error) {
    return (
      <div className="h-full rounded-lg overflow-hidden border border-[var(--border)]">
        <MapContainer center={center} zoom={15} className="h-full w-full" scrollWheelZoom={true}>
          <TileLayer url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png" attribution="&copy; CartoDB" />
        </MapContainer>
      </div>
    );
  }

  const eid = advisory.event_identification || {};
  const route = advisory.route_advisory || {};
  const primary = route.primary_evacuation_route;
  const affectedSeg = eid.affected_segment || "";

  const incidentCoord = INCIDENT_COORDS[affectedSeg] || center;
  const affectedLine = SEGMENT_COORDS[affectedSeg] || null;
  const primaryId = primary?.primary_route_id;
  const primaryLine = primaryId ? SEGMENT_COORDS[primaryId] : null;
  const secondaryLines = (primary?.secondary_routes || []).map((r) => SEGMENT_COORDS[r.segment_id]).filter(Boolean);

  return (
    <div className="h-full rounded-lg overflow-hidden border border-[var(--border)]">
      <MapContainer center={incidentCoord} zoom={16} className="h-full w-full" scrollWheelZoom={true}>
        <TileLayer url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png" attribution="&copy; CartoDB" />
        <FlyTo center={incidentCoord} />

        {affectedLine && <Polyline positions={affectedLine} pathOptions={{ color: "#DC2626", weight: 7, opacity: 0.85 }} />}
        {primaryLine && <Polyline positions={primaryLine} pathOptions={{ color: "#16A34A", weight: 5, opacity: 0.9, dashArray: "12,6" }} />}
        {secondaryLines.map((line, idx) => <Polyline key={idx} positions={line} pathOptions={{ color: "#2563EB", weight: 4, opacity: 0.7, dashArray: "8,8" }} />)}

        <Marker position={incidentCoord} icon={incidentIcon}>
          <Popup><strong>{eid.location || affectedSeg}</strong></Popup>
        </Marker>
      </MapContainer>
    </div>
  );
}
