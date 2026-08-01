import { cn } from "../lib/utils";

/**
 * 替代道路候選評估表
 *
 * 對應交付要求「替代路徑建議：主要疏散、次要替代，並說明排除其他候選之理由」與
 * 模組 4「為何排除特定替代道路之推理理由」。原本 traffic_math 已經算出每個候選的
 * 容量／相交／上下游判定，但沒有往上傳到畫面，評審看不到排除依據。
 */

const ROLE_LABEL = {
  primary: { text: "主疏散", cls: "bg-[var(--status-success)] text-[var(--primary-foreground)]" },
  secondary: { text: "次要", cls: "bg-[var(--status-info)] text-[var(--primary-foreground)]" },
  excluded: { text: "排除", cls: "bg-[var(--secondary)] text-[var(--muted-foreground)]" },
};

function yesNo(value) {
  return value ? "✓" : "—";
}

export default function RouteCandidateTable({ candidates, upstream, compact = true }) {
  if (!candidates?.length) return null;

  const rows = [...candidates].sort((a, b) => {
    const order = { primary: 0, secondary: 1, excluded: 2 };
    return (order[a.role] ?? 3) - (order[b.role] ?? 3);
  });

  return (
    <details className={cn(compact && "mt-1")}>
      <summary className="text-xs text-[var(--muted-foreground)] cursor-pointer hover:text-[var(--foreground)] transition">
        候選替代道路評估（{rows.length} 條，含排除理由）
      </summary>

      {upstream?.detail && (
        <p className="mt-1.5 text-xs text-[var(--muted-foreground)] leading-relaxed">
          <span className="font-medium">上下游判定：</span>
          {upstream.detail}
          {upstream.method && `（判定方法：${upstream.method}）`}
          {upstream.upstream_intersections?.length > 0 &&
            `；上游路口：${upstream.upstream_intersections.join("、")}`}
        </p>
      )}

      <div className="mt-1.5 overflow-x-auto">
        <table className="w-full text-xs border-collapse">
          <caption className="sr-only">替代道路候選評估與排除理由</caption>
          <thead>
            <tr className="text-[var(--muted-foreground)] text-left">
              <th scope="col" className="py-1 pr-2 font-medium">路段</th>
              <th scope="col" className="py-1 pr-2 font-medium">容量</th>
              <th scope="col" className="py-1 pr-2 font-medium">飽和度</th>
              <th scope="col" className="py-1 pr-2 font-medium" title="是否與事故路段直接相交">
                相交
              </th>
              <th scope="col" className="py-1 pr-2 font-medium" title="相交路口是否位於事故點上游">
                上游
              </th>
              <th scope="col" className="py-1 font-medium">判定</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => {
              const role = ROLE_LABEL[c.role] || ROLE_LABEL.excluded;
              return (
                <tr key={c.segment_id} className="border-t border-[var(--border)] align-top">
                  <td className="py-1.5 pr-2">
                    <div className="flex items-center gap-1.5">
                      <span
                        className={cn(
                          "text-[10px] px-1 py-0.5 rounded-sm font-bold shrink-0",
                          role.cls,
                        )}
                      >
                        {role.text}
                      </span>
                      <span className="whitespace-nowrap">{c.name}</span>
                    </div>
                  </td>
                  <td
                    className={cn(
                      "py-1.5 pr-2 font-mono whitespace-nowrap",
                      !c.capacity_ok && "text-[var(--status-error)]",
                    )}
                  >
                    {c.capacity_vph}
                  </td>
                  <td className="py-1.5 pr-2 font-mono whitespace-nowrap">
                    {c.saturation_score == null
                      ? "無資料"
                      : `${Math.round(c.saturation_score * 100)}%`}
                  </td>
                  <td className="py-1.5 pr-2">{yesNo(c.is_intersecting)}</td>
                  <td className="py-1.5 pr-2">{yesNo(c.is_upstream)}</td>
                  <td className="py-1.5 text-[var(--muted-foreground)] leading-relaxed">
                    {c.reason}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </details>
  );
}
