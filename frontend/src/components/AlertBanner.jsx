import { AlertTriangle, X } from "lucide-react";

export default function AlertBanner({ alert, onDismiss }) {
  if (!alert) return null;

  const styles = {
    A: "bg-red-900/90 border-red-500 text-red-100",
    B: "bg-yellow-900/90 border-yellow-500 text-yellow-100",
    error: "bg-red-900/90 border-red-500 text-red-100",
  };

  const labels = {
    A: "A 級癱瘓警報",
    B: "B 級壅擠警報",
    error: "系統錯誤",
  };

  return (
    <div className={`border-b-2 px-6 py-3 flex items-center justify-between animate-pulse ${styles[alert.level] || styles.error}`}>
      <div className="flex items-center gap-3">
        <AlertTriangle className="w-5 h-5" />
        <span className="font-bold">{labels[alert.level] || "警報"}</span>
        <span className="text-sm opacity-90">{alert.summary}</span>
        {alert.event_id && <span className="text-xs opacity-60 ml-2">[{alert.event_id}]</span>}
      </div>
      <button onClick={onDismiss} className="hover:opacity-70">
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}
