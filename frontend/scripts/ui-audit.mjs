/**
 * UI 稽核腳本（Playwright + axe-core）
 *
 * 走訪三個分頁，於多組視窗尺寸下擷取：
 *   - console error / page error / 失敗請求
 *   - axe-core 可及性違規（含對比度）
 *   - 水平溢出、觸控目標尺寸、鍵盤 focus 可見性
 *   - 各分頁截圖
 *
 * 用法：node scripts/ui-audit.mjs [baseURL]
 */
import { chromium } from "@playwright/test";
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const require = createRequire(import.meta.url);
const axePath = require.resolve("axe-core/axe.min.js");
const axeSource = await import("node:fs").then((fs) => fs.promises.readFile(axePath, "utf8"));

const BASE = process.argv[2] || "http://127.0.0.1:3000";
const OUT = path.resolve("ui-audit-out");

const TABS = [
  { id: "dashboard", label: "即時儀表板" },
  { id: "incidents", label: "事件處置與建議書" },
  { id: "chat", label: "AI 策略顧問" },
];

const VIEWPORTS = [
  { name: "desktop-1920", width: 1920, height: 1080 },
  { name: "laptop-1440", width: 1440, height: 900 },
  { name: "laptop-1280", width: 1280, height: 800 },
  { name: "tablet-768", width: 768, height: 1024 },
  { name: "mobile-390", width: 390, height: 844 },
];

const report = { base: BASE, generatedAt: new Date().toISOString(), viewports: [] };

const browser = await chromium.launch();
await mkdir(OUT, { recursive: true });

for (const vp of VIEWPORTS) {
  const context = await browser.newContext({
    viewport: { width: vp.width, height: vp.height },
    locale: "zh-TW",
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();

  const consoleErrors = [];
  const failedRequests = [];
  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warning") {
      consoleErrors.push(`[${m.type()}] ${m.text().slice(0, 300)}`);
    }
  });
  page.on("pageerror", (e) => consoleErrors.push(`[pageerror] ${e.message.slice(0, 300)}`));
  page.on("requestfailed", (r) =>
    failedRequests.push(`${r.method()} ${r.url().slice(0, 160)} — ${r.failure()?.errorText}`),
  );

  await page.goto(BASE, { waitUntil: "networkidle" }).catch(() => {});
  // 等路網資料輪詢回來
  await page.waitForTimeout(4000);

  const vpResult = { viewport: vp.name, size: `${vp.width}x${vp.height}`, tabs: [] };

  for (const tab of TABS) {
    const navBtn = page.getByRole("button", { name: tab.label });
    if (await navBtn.count()) {
      await navBtn.first().click();
      await page.waitForTimeout(2500);
    }

    await page.addScriptTag({ content: axeSource });
    const axe = await page.evaluate(async () => {
      const res = await window.axe.run(document, {
        resultTypes: ["violations"],
        runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"] },
      });
      return res.violations.map((v) => ({
        id: v.id,
        impact: v.impact,
        help: v.help,
        nodes: v.nodes.slice(0, 4).map((n) => ({
          target: n.target.join(" "),
          summary: (n.failureSummary || "").replace(/\s+/g, " ").slice(0, 260),
        })),
        total: v.nodes.length,
      }));
    });

    const layout = await page.evaluate(() => {
      const de = document.documentElement;
      const overflowX = de.scrollWidth - de.clientWidth;

      // 水平溢出元素
      const overflowing = [];
      for (const el of document.querySelectorAll("body *")) {
        const r = el.getBoundingClientRect();
        if (r.width === 0) continue;
        if (r.right > de.clientWidth + 2 || r.left < -2) {
          overflowing.push(
            `${el.tagName.toLowerCase()}.${(el.className || "").toString().split(" ")[0]} right=${Math.round(r.right)}`,
          );
        }
        if (overflowing.length > 8) break;
      }

      // 觸控目標 < 24x24（WCAG 2.2 最低）與 < 44x44（行動裝置建議）
      const small = [];
      for (const el of document.querySelectorAll("button, a[href], [role='button'], input")) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        if (r.width < 24 || r.height < 24) {
          small.push(
            `${el.tagName.toLowerCase()} "${(el.getAttribute("title") || el.textContent || "").trim().slice(0, 24)}" ${Math.round(r.width)}x${Math.round(r.height)}`,
          );
        }
      }

      // 語意結構
      const headings = [...document.querySelectorAll("h1,h2,h3,h4,h5,h6")].map(
        (h) => `${h.tagName}: ${h.textContent.trim().slice(0, 30)}`,
      );
      const landmarks = {
        main: document.querySelectorAll("main").length,
        nav: document.querySelectorAll("nav").length,
        header: document.querySelectorAll("header").length,
        tablist: document.querySelectorAll("[role='tablist']").length,
        tab: document.querySelectorAll("[role='tab']").length,
        ariaLive: document.querySelectorAll("[aria-live]").length,
        skipLink: [...document.querySelectorAll("a")].some((a) =>
          (a.getAttribute("href") || "").startsWith("#"),
        ),
      };

      return {
        overflowX,
        overflowing: [...new Set(overflowing)],
        smallTargets: [...new Set(small)],
        headings,
        landmarks,
        bodyScrollHeight: document.body.scrollHeight,
      };
    });

    // 鍵盤走訪：前 12 個 focus 停靠點與 outline 可見性
    const focusChain = await page.evaluate(() => []);
    await page.evaluate(() => document.body.focus());
    const tabStops = [];
    for (let i = 0; i < 12; i++) {
      await page.keyboard.press("Tab");
      const info = await page.evaluate(() => {
        const el = document.activeElement;
        if (!el || el === document.body) return null;
        const cs = getComputedStyle(el);
        return {
          tag: el.tagName.toLowerCase(),
          name: (el.getAttribute("aria-label") || el.textContent || el.getAttribute("title") || "")
            .trim()
            .slice(0, 30),
          outline: cs.outlineStyle === "none" ? "none" : cs.outlineWidth,
          boxShadow: cs.boxShadow === "none" ? "none" : "present",
        };
      });
      if (info) tabStops.push(info);
    }

    const shot = path.join(OUT, `${vp.name}-${tab.id}.png`);
    await page.screenshot({ path: shot, fullPage: vp.name === "laptop-1440" });

    vpResult.tabs.push({
      tab: tab.id,
      axeViolations: axe,
      layout,
      tabStops,
      screenshot: path.relative(process.cwd(), shot),
      focusChain,
    });
  }

  vpResult.consoleErrors = [...new Set(consoleErrors)];
  vpResult.failedRequests = [...new Set(failedRequests)];
  report.viewports.push(vpResult);
  await context.close();
  console.log(`done ${vp.name}`);
}

await browser.close();
await writeFile(path.join(OUT, "report.json"), JSON.stringify(report, null, 2), "utf8");

// 摘要輸出
for (const vp of report.viewports) {
  console.log(`\n===== ${vp.viewport} (${vp.size}) =====`);
  if (vp.consoleErrors.length) console.log("console:", vp.consoleErrors.slice(0, 6));
  if (vp.failedRequests.length) console.log("failedRequests:", vp.failedRequests.slice(0, 6));
  for (const t of vp.tabs) {
    console.log(`-- ${t.tab}`);
    console.log(
      "   axe:",
      t.axeViolations.map((v) => `${v.id}(${v.impact}x${v.total})`).join(", ") || "none",
    );
    console.log("   overflowX:", t.layout.overflowX, "overflowing:", t.layout.overflowing.slice(0, 4));
    console.log("   smallTargets:", t.layout.smallTargets.slice(0, 6));
    console.log("   headings:", t.layout.headings.slice(0, 6));
    console.log("   landmarks:", JSON.stringify(t.layout.landmarks));
    console.log(
      "   tabStops:",
      t.tabStops.map((s) => `${s.name || s.tag}[outline=${s.outline}]`).join(" > "),
    );
  }
}
