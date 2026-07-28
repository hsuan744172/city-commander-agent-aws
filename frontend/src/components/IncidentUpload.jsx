import { useState, useRef } from "react";
import { Upload, Loader2, CheckCircle2, AlertCircle, FileJson } from "lucide-react";

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
      const data = await res.json();
      if (data.error) {
        setStatus("error");
        setDetail(data.error);
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
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
      <h2 className="text-sm font-semibold text-gray-200 mb-1">突發事件注入</h2>
      <p className="text-xs text-gray-500 mb-4">上傳 live_incidents.json，系統將於數秒內完成路網重規劃並產出建議書</p>

      <label
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={`flex flex-col items-center justify-center gap-3 p-10 border-2 border-dashed rounded-xl cursor-pointer transition-all ${
          dragOver ? "border-blue-400 bg-blue-950/30" : "border-gray-700 hover:border-blue-500 hover:bg-blue-950/10"
        }`}
      >
        {status === "uploading" ? (
          <Loader2 className="w-12 h-12 text-blue-400 animate-spin" />
        ) : (
          <div className="bg-gray-800 p-4 rounded-full">
            <Upload className="w-8 h-8 text-gray-400" />
          </div>
        )}
        <div className="text-center">
          <span className="text-sm text-gray-300 font-medium">
            {status === "uploading" ? "AI 決策運算中..." : "拖曳或點擊上傳 live_incidents.json"}
          </span>
        </div>
        <input ref={fileRef} type="file" accept=".json" onChange={(e) => processFile(e.target.files?.[0])} className="hidden" disabled={status === "uploading"} />
      </label>

      {status && status !== "uploading" && (
        <div className={`mt-4 flex items-center gap-2 px-4 py-3 rounded-lg text-sm ${
          status === "success" ? "bg-green-900/30 border border-green-700 text-green-200" : "bg-red-900/30 border border-red-700 text-red-200"
        }`}>
          {status === "success" ? <CheckCircle2 className="w-4 h-4 shrink-0" /> : <AlertCircle className="w-4 h-4 shrink-0" />}
          <span>{detail}</span>
        </div>
      )}
    </div>
  );
}
