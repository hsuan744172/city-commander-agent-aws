const DEFAULT_OPTIONS = {
  horizontalSpacing: 22,
  verticalSpacing: 24,
  padding: 18,
  minRoadWidth: 5.8,
  maxRoadWidth: 9.2,
};

export function getRoadAxis(road) {
  const direction = road?.flow_direction || "";
  if (direction.includes("東西")) return "horizontal";
  if (direction.includes("南北")) return "vertical";
  return "unknown";
}

export function buildSchematicRoadLayout(roadNetwork, options = {}) {
  const config = { ...DEFAULT_OPTIONS, ...options };
  const roads = Array.isArray(roadNetwork) ? roadNetwork : [];
  const roadByName = new Map(roads.map((road) => [road.name, road]));
  const roadById = new Map(roads.map((road) => [road.segment_id, road]));

  const horizontalRoads = roads.filter((road) => getRoadAxis(road) === "horizontal");
  const verticalRoads = roads.filter((road) => getRoadAxis(road) === "vertical");

  const horizontalIndex = new Map(horizontalRoads.map((road, index) => [road.name, index]));
  const verticalIndex = new Map(verticalRoads.map((road, index) => [road.name, index]));

  const horizontalCenter = (horizontalRoads.length - 1) / 2;
  const verticalCenter = (verticalRoads.length - 1) / 2;

  const horizontalZByName = new Map(
    horizontalRoads.map((road, index) => [
      road.name,
      (index - horizontalCenter) * config.horizontalSpacing,
    ]),
  );

  const verticalXByName = new Map(
    verticalRoads.map((road, index) => [
      road.name,
      (index - verticalCenter) * config.verticalSpacing,
    ]),
  );

  const capacityValues = roads.map((road) => Number(road.capacity_vph) || 0);
  const minCapacity = Math.min(...capacityValues);
  const maxCapacity = Math.max(...capacityValues);

  const widthForCapacity = (capacity) => {
    if (maxCapacity === minCapacity) return (config.minRoadWidth + config.maxRoadWidth) / 2;
    const ratio = ((Number(capacity) || minCapacity) - minCapacity) / (maxCapacity - minCapacity);
    return config.minRoadWidth + ratio * (config.maxRoadWidth - config.minRoadWidth);
  };

  const intersections = [];
  const intersectionKeySet = new Set();

  const addIntersection = (horizontalRoad, verticalRoad) => {
    const x = verticalXByName.get(verticalRoad.name);
    const z = horizontalZByName.get(horizontalRoad.name);
    if (x == null || z == null) return null;

    const key = `${horizontalRoad.segment_id}:${verticalRoad.segment_id}`;
    if (intersectionKeySet.has(key)) {
      return intersections.find((item) => item.key === key);
    }

    const intersection = {
      key,
      id: `${horizontalRoad.name} / ${verticalRoad.name}`,
      horizontalRoadId: horizontalRoad.segment_id,
      verticalRoadId: verticalRoad.segment_id,
      horizontalRoadName: horizontalRoad.name,
      verticalRoadName: verticalRoad.name,
      x,
      z,
      point: [x, 0, z],
    };

    intersectionKeySet.add(key);
    intersections.push(intersection);
    return intersection;
  };

  horizontalRoads.forEach((horizontalRoad) => {
    horizontalRoad.intersections?.forEach((intersectionName) => {
      const verticalRoad = roadByName.get(intersectionName);
      if (verticalRoad && getRoadAxis(verticalRoad) === "vertical") {
        addIntersection(horizontalRoad, verticalRoad);
      }
    });
  });

  verticalRoads.forEach((verticalRoad) => {
    verticalRoad.intersections?.forEach((intersectionName) => {
      const horizontalRoad = roadByName.get(intersectionName);
      if (horizontalRoad && getRoadAxis(horizontalRoad) === "horizontal") {
        addIntersection(horizontalRoad, verticalRoad);
      }
    });
  });

  const layoutRoads = roads
    .map((road) => {
      const axis = getRoadAxis(road);
      const connectedIntersections = intersections.filter(
        (intersection) =>
          intersection.horizontalRoadId === road.segment_id ||
          intersection.verticalRoadId === road.segment_id,
      );

      if (axis === "horizontal") {
        const z = horizontalZByName.get(road.name);
        const xs = connectedIntersections.map((intersection) => intersection.x);
        const fallbackMinX = -((verticalRoads.length - 1) * config.verticalSpacing) / 2;
        const fallbackMaxX = ((verticalRoads.length - 1) * config.verticalSpacing) / 2;
        const minX = (xs.length ? Math.min(...xs) : fallbackMinX) - config.padding;
        const maxX = (xs.length ? Math.max(...xs) : fallbackMaxX) + config.padding;

        return {
          id: road.segment_id,
          name: road.name,
          axis,
          source: road,
          width: widthForCapacity(road.capacity_vph),
          active: false,
          from: [minX, 0, z],
          to: [maxX, 0, z],
          intersections: connectedIntersections,
        };
      }

      if (axis === "vertical") {
        const x = verticalXByName.get(road.name);
        const zs = connectedIntersections.map((intersection) => intersection.z);
        const fallbackMinZ = -((horizontalRoads.length - 1) * config.horizontalSpacing) / 2;
        const fallbackMaxZ = ((horizontalRoads.length - 1) * config.horizontalSpacing) / 2;
        const minZ = (zs.length ? Math.min(...zs) : fallbackMinZ) - config.padding;
        const maxZ = (zs.length ? Math.max(...zs) : fallbackMaxZ) + config.padding;

        return {
          id: road.segment_id,
          name: road.name,
          axis,
          source: road,
          width: widthForCapacity(road.capacity_vph),
          active: false,
          from: [x, 0, minZ],
          to: [x, 0, maxZ],
          intersections: connectedIntersections,
        };
      }

      return null;
    })
    .filter(Boolean);

  return {
    roads: layoutRoads,
    intersections,
    horizontalRoads,
    verticalRoads,
    roadById,
    roadByName,
    horizontalIndex,
    verticalIndex,
  };
}

export function mergeRoadStatus(layout, statusPayload) {
  const statusSegments = Array.isArray(statusPayload?.segments) ? statusPayload.segments : [];
  const statusBySegmentId = new Map(
    statusSegments.map((segment) => [segment.segment_id, segment]),
  );

  const roads = (layout?.roads || []).map((road) => {
    const status = statusBySegmentId.get(road.id) || null;
    return {
      ...road,
      status,
      level: status?.level || "Unknown",
      saturationScore: status?.saturation_score ?? null,
      avgSpeed: status?.avg_speed ?? null,
      vehicleCount: status?.vehicle_count ?? null,
      laneStatus: status?.lane_status || "",
      active: status?.level === "A" || status?.level === "B",
    };
  });

  const roadLevelById = new Map(roads.map((road) => [road.id, road.level]));
  const intersections = (layout?.intersections || []).map((intersection) => {
    const connectedLevels = [
      roadLevelById.get(intersection.horizontalRoadId),
      roadLevelById.get(intersection.verticalRoadId),
    ];
    const level = connectedLevels.includes("A")
      ? "A"
      : connectedLevels.includes("B")
        ? "B"
        : "Normal";

    return {
      ...intersection,
      level,
      active: level === "A" || level === "B",
    };
  });

  return {
    ...layout,
    roads,
    intersections,
    status: {
      simTime: statusPayload?.sim_time || statusPayload?.timestamp || "",
      dataAsOf: statusPayload?.data_as_of || "",
      totalSegments: statusPayload?.total_segments || statusSegments.length,
    },
  };
}
