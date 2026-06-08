import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getDashboard, getAlerts, getRepairQueue, resolveAlert } from "../api/client";

export default function DashboardPage() {
  const qc = useQueryClient();

  const { data: dashboard } = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => getDashboard().then((r) => r.data),
    refetchInterval: 30_000,
  });

  const { data: alerts = [] } = useQuery({
    queryKey: ["alerts"],
    queryFn: () => getAlerts(false).then((r) => r.data),
    refetchInterval: 30_000,
  });

  const { data: repairQueue = [] } = useQuery({
    queryKey: ["repair-queue"],
    queryFn: () => getRepairQueue().then((r) => r.data),
    refetchInterval: 30_000,
  });

  const handleResolve = async (id: string) => {
    await resolveAlert(id);
    qc.invalidateQueries({ queryKey: ["alerts"] });
  };

  const ALERT_COLOR: Record<string, string> = {
    score_drop: "bg-red-50 border-red-200 text-red-800",
    repair_queue_depth: "bg-orange-50 border-orange-200 text-orange-800",
    repair_queue_age: "bg-yellow-50 border-yellow-200 text-yellow-800",
  };

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-800">Ops Dashboard</h1>
        {dashboard && (
          <span className="text-xs text-slate-400">
            as of {new Date(dashboard.as_of).toLocaleTimeString()}
          </span>
        )}
      </div>

      {/* Top stats */}
      {dashboard && (
        <div className="grid grid-cols-3 gap-4">
          <StatCard label="Open Alerts" value={dashboard.open_alerts} warn={dashboard.open_alerts > 0} />
          <StatCard label="Repair Queue" value={dashboard.repair_queue_depth} warn={dashboard.repair_queue_depth > 10} />
          <StatCard label="Skills Active" value={dashboard.skills.length} />
        </div>
      )}

      {/* Per-skill table */}
      {dashboard && (
        <section>
          <h2 className="text-base font-semibold text-slate-700 mb-3">Skill Performance</h2>
          <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-500 text-xs uppercase tracking-wide">
                <tr>
                  {["Skill", "Total", "Approved", "Rejected", "Repair", "Avg Score", "Avg Cost"].map(
                    (h) => (
                      <th key={h} className="px-4 py-2 text-left font-medium">
                        {h}
                      </th>
                    )
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {dashboard.skills.map((s) => (
                  <tr key={s.skill_type} className="hover:bg-slate-50">
                    <td className="px-4 py-2 font-medium text-indigo-700">
                      {s.skill_type.replace("_", " ")}
                    </td>
                    <td className="px-4 py-2 text-slate-600">{s.total_generations}</td>
                    <td className="px-4 py-2 text-green-600">{s.approved}</td>
                    <td className="px-4 py-2 text-red-500">{s.rejected}</td>
                    <td className="px-4 py-2 text-orange-500">{s.needs_repair}</td>
                    <td className="px-4 py-2 text-slate-600">
                      {s.avg_eval_score !== null ? s.avg_eval_score.toFixed(3) : "—"}
                    </td>
                    <td className="px-4 py-2 text-slate-600">
                      {s.avg_cost_usd !== null ? `$${s.avg_cost_usd.toFixed(4)}` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Alerts */}
      <section>
        <h2 className="text-base font-semibold text-slate-700 mb-3">
          Open Alerts{" "}
          {alerts.length > 0 && (
            <span className="ml-1 bg-red-500 text-white text-xs px-1.5 rounded-full">
              {alerts.length}
            </span>
          )}
        </h2>
        {alerts.length === 0 ? (
          <div className="bg-green-50 border border-green-200 rounded-xl p-4 text-green-700 text-sm">
            ✓ No open alerts
          </div>
        ) : (
          <div className="space-y-2">
            {alerts.map((a) => (
              <div
                key={a.id}
                className={`flex items-start gap-3 border rounded-xl px-4 py-3 text-sm ${
                  ALERT_COLOR[a.alert_type] ?? "bg-slate-50 border-slate-200"
                }`}
              >
                <div className="flex-1">
                  <span className="font-semibold capitalize">
                    {a.alert_type.replace(/_/g, " ")}
                  </span>
                  {a.skill_type && (
                    <span className="ml-2 text-xs opacity-70">[{a.skill_type}]</span>
                  )}
                  <p className="opacity-80 mt-0.5">{a.message}</p>
                </div>
                <button
                  onClick={() => handleResolve(a.id)}
                  className="text-xs underline opacity-70 hover:opacity-100 whitespace-nowrap"
                >
                  Resolve
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Repair queue */}
      <section>
        <h2 className="text-base font-semibold text-slate-700 mb-3">
          Repair Queue{" "}
          {repairQueue.length > 0 && (
            <span className="ml-1 bg-orange-500 text-white text-xs px-1.5 rounded-full">
              {repairQueue.length}
            </span>
          )}
        </h2>
        {repairQueue.length === 0 ? (
          <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 text-slate-500 text-sm">
            Queue is empty
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-500 text-xs uppercase">
                <tr>
                  {["Generation", "Skill", "Retries", "Error", "Age"].map((h) => (
                    <th key={h} className="px-4 py-2 text-left font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {repairQueue.map((r) => (
                  <tr key={r.id} className="hover:bg-slate-50">
                    <td className="px-4 py-2 font-mono text-xs text-slate-500">
                      {r.generation_id.slice(0, 8)}
                    </td>
                    <td className="px-4 py-2 text-indigo-700">
                      {r.skill_type.replace("_", " ")}
                    </td>
                    <td className="px-4 py-2 text-slate-600">{r.retry_count}</td>
                    <td className="px-4 py-2 text-red-500 text-xs max-w-xs truncate">
                      {r.last_error ?? "—"}
                    </td>
                    <td className="px-4 py-2 text-slate-400 text-xs">
                      {new Date(r.created_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function StatCard({
  label,
  value,
  warn = false,
}: {
  label: string;
  value: number;
  warn?: boolean;
}) {
  return (
    <div
      className={`rounded-xl border p-4 ${
        warn ? "bg-red-50 border-red-200" : "bg-white border-slate-200"
      }`}
    >
      <div className={`text-3xl font-bold ${warn ? "text-red-700" : "text-slate-800"}`}>
        {value}
      </div>
      <div className="text-sm text-slate-500 mt-1">{label}</div>
    </div>
  );
}
