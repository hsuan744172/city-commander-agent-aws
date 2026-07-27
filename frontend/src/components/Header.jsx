import { Activity, Shield } from "lucide-react";

export default function Header() {
  return (
    <header className="bg-gray-900 border-b border-gray-800 px-6 py-3 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <div className="bg-blue-600 p-2 rounded-lg">
          <Shield className="w-6 h-6 text-white" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-white">城市應變指揮官</h1>
          <p className="text-xs text-gray-400">AI Traffic Command Center v2.0</p>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Activity className="w-4 h-4 text-green-400 animate-pulse" />
        <span className="text-xs text-green-400">系統運作中</span>
      </div>
    </header>
  );
}
