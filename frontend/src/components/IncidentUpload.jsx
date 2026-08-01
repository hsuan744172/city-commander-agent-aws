import { useState, useRef } from "react";
import { Upload, Loader2, CheckCircle2, AlertCircle } from "lucide-react";
import { cn } from "../lib/utils";

export default function IncidentUpload({ onResult }) {
  const [status, setStatus] = useState(null);
  const [detail, setDetail] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef(null);

  const processFile = async (file) => {
    if (!file) return;
    setStatus("uploading");
    setDetail(file.name);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("/api/incidents/upload", { method: "POST", body: formData });
      const isJson = res.headers.get("content-type")?.includes("application/json");
      const data = isJson ? await res.json() : null;

      if (!res.ok || data?.error) {
        setStatus("error");
        setDetail(
          data?.error
            || (res.status === 504
              ? "伺服器處理逾時，請確認檔案為事件 JSON 並減少事件數。"
              : `上傳失敗（HTTP ${res.status}），請稍後再試。`)
        );
      } else if ((data?.failed || 0) > 0) {
        setStatus("error");
        setDetail(`${data.processed}/${data.total_incidents} 件事件完成，${data.failed} 件處理失敗，請檢查事件內容後重試。`);
        onResult(data);
      } else {
        setStatus("success");
        setDetail(`${data.processed}/${data.total_incidents} 件事件已完成路網重規劃`);
        onResult(data);
      }
    } catch (err) {
      setStatus("error");
      setDetail(err.message);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file?.name.endsWith(".json")) processFile(file);
    else { setStatus("error"); setDetail("僅支援 .json 檔案"); }
  };

  return (
    <div className="bg-[var(--card)] rounded-lg border border-[var(--border)] p-5">
      <h2 className="text-sm font-semibold mb-1">突發事件注入</h2>
      <p className="text-xs text-[var(--muted-foreground)] mb-4">上傳 live_incidents.json，系統將於數秒內完成路網重規劃並產出建議書</p>

      <label
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={cn(
          "flex flex-col items-center justify-center gap-3 p-10 border-2 border-dashed rounded-lg cursor-pointer transition-all",
          dragOver
            ? "border-[var(--primary)] bg-[var(--primary)]/10"
            : "border-[var(--border)] hover:border-[var(--primary)] hover:bg-[var(--primary)]/5"
        )}
      >
        {status === "uploading" ? (
          <Loader2 className="w-12 h-12 text-[var(--primary)] animate-spin" />
        ) : (
          <div className="bg-[var(--secondary)] p-4 rounded-full">
            <Upload className="w-8 h-8 text-[var(--muted-foreground)]" />
          </div>
        )}
        <div className="text-center">
          <span className="text-sm font-medium">
            {status === "uploading" ? "AI 決策運算中..." : "拖曳或點擊上傳 live_incidents.json"}
          </span>
        </div>
        <input ref={fileRef} type="file" accept=".json" onChange={(e) => processFile(e.target.files?.[0])} className="hidden" disabled={status === "uploading"} />
      </label>

      {status && status !== "uploading" && (
        <div className={cn(
          "mt-4 flex items-center gap-2 px-4 py-3 rounded-md text-sm",
          status === "success"
            ? "bg-[var(--status-success)]/10 border border-[var(--status-success)]/30 text-[var(--status-success)]"
            : "bg-[var(--status-error)]/10 border border-[var(--status-error)]/30 text-[var(--status-error)]"
        )}>
          {status === "success" ? <CheckCircle2 className="w-4 h-4 shrink-0" /> : <AlertCircle className="w-4 h-4 shrink-0" />}
          <span>{detail}</span>
        </div>
      )}
    </div>
  );
}
