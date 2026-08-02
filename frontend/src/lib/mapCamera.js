/**
 * 地圖相機導播 — 突發事件時自動飛抵、聚焦、環繞，直到指揮官介入接手
 *
 * 流程：
 *   focus()  → flyTo 飛到事件點（狀態 flying）
 *   飛抵後   → 以每秒固定角度繞著事件點旋轉（狀態 orbiting）
 *   人為操作 → 立刻停下把控制權交還（狀態 released）
 *
 * 「人為操作」刻意綁在地圖容器的 DOM 事件上，不用 MapLibre 的 dragstart /
 * zoomstart 判斷：我們自己的 flyTo 與每幀 setBearing 也會發出那些地圖事件，
 * 得再去猜 originalEvent 有沒有值才能分辨；DOM 的 pointerdown / wheel 只有
 * 真人（含點擊右上角縮放鈕）才會產生，程式移動相機永遠不會誤觸。
 */

export const CAMERA_FOCUS = {
  /** 聚焦後的鏡位 */
  zoom: 16.4,
  pitch: 62,
  /** 飛行時間（毫秒） */
  flyDuration: 2600,
  /** flyTo 的飛行曲線，越大越像「拉遠再俯衝」 */
  flyCurve: 1.5,
  /** 環繞速度（度／秒）。6 度約 60 秒繞一圈 */
  orbitDegreesPerSecond: 6,
};

const USER_INPUT_EVENTS = ["pointerdown", "wheel", "touchstart", "dblclick", "keydown"];

/** 使用者要求減少動態時，不做飛行與環繞，直接跳到位 */
function prefersReducedMotion() {
  return Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches);
}

/**
 * @param {import("maplibre-gl").Map} map
 * @param {{ onStateChange?: (state: "idle"|"flying"|"orbiting"|"held"|"released") => void }} options
 */
export function createCameraDirector(map, { onStateChange } = {}) {
  let state = "idle";
  let rafId = null;
  // null = 還沒有第一幀。不能用 0 當哨兵：時間戳本身可能是 0，
  // 那會讓每一幀都被當成「第一幀」而算出 0 秒差，鏡頭永遠不動。
  let lastFrameTime = null;
  let disposed = false;
  // 每次 focus 換一個世代編號：舊的 moveend 回呼會因為世代不符而失效。
  // 沒有這道保險時，前一次飛行被新的 focus 中斷所產生的 moveend
  // 會在新飛行途中就啟動環繞，兩個動畫互相打斷。
  let generation = 0;

  const setState = (next) => {
    if (state === next) return;
    state = next;
    onStateChange?.(next);
  };

  const cancelOrbit = () => {
    if (rafId !== null) {
      cancelAnimationFrame(rafId);
      rafId = null;
    }
    lastFrameTime = null;
  };

  const orbitFrame = (now) => {
    if (disposed) return;
    // 用時間差推進角度，不同螢幕刷新率下的旋轉速度才一致
    const elapsed = lastFrameTime === null ? 0 : (now - lastFrameTime) / 1000;
    lastFrameTime = now;
    map.setBearing(map.getBearing() + CAMERA_FOCUS.orbitDegreesPerSecond * elapsed);
    rafId = requestAnimationFrame(orbitFrame);
  };

  const startOrbit = () => {
    if (disposed) return;
    cancelOrbit();
    setState("orbiting");
    rafId = requestAnimationFrame(orbitFrame);
  };

  /** 停止自動導播。reason = "user" 代表指揮官接手 */
  const release = (reason = "user") => {
    generation += 1;
    cancelOrbit();
    try {
      map.stop(); // 中斷還在進行的 flyTo
    } catch {
      /* 地圖已銷毀時忽略 */
    }
    setState(reason === "user" ? "released" : "idle");
  };

  const handleUserInput = () => {
    if (state === "flying" || state === "orbiting") release("user");
  };

  const container = map.getContainer();
  for (const type of USER_INPUT_EVENTS) {
    container.addEventListener(type, handleUserInput, { capture: true, passive: true });
  }

  /**
   * 飛到目標並開始環繞
   * @param {{ center: [number, number], bearing?: number, zoom?: number, pitch?: number, orbit?: boolean }} target
   */
  const focus = (target) => {
    if (disposed || !target?.center) return;
    const reduced = prefersReducedMotion();
    const gen = ++generation;

    cancelOrbit();
    setState("flying");
    map.stop(); // 先收掉前一段動畫，殘留的 moveend 會在這裡同步發完
    map.flyTo({
      center: target.center,
      zoom: target.zoom ?? CAMERA_FOCUS.zoom,
      pitch: target.pitch ?? CAMERA_FOCUS.pitch,
      bearing: target.bearing ?? map.getBearing(),
      curve: CAMERA_FOCUS.flyCurve,
      duration: reduced ? 0 : CAMERA_FOCUS.flyDuration,
    });

    // duration 0 時 flyTo 會同步跳到位、moveend 也已經發完，不能再等事件
    if (reduced) {
      setState("held");
      return;
    }

    map.once("moveend", () => {
      // 世代不符（已被新的 focus 取代）或已被接手，就不要接著環繞
      if (disposed || gen !== generation || state !== "flying") return;
      if (target.orbit === false) setState("held");
      else startOrbit();
    });
  };

  const dispose = () => {
    disposed = true;
    cancelOrbit();
    for (const type of USER_INPUT_EVENTS) {
      container.removeEventListener(type, handleUserInput, { capture: true });
    }
  };

  return {
    focus,
    release,
    startOrbit,
    dispose,
    getState: () => state,
    isAutoDriving: () => state === "flying" || state === "orbiting",
  };
}
