import { Fragment, useState } from "react";
import EvalBadge from "./EvalBadge.jsx";
import RiskMeter from "./RiskMeter.jsx";

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtDuration(secs) {
  if (secs == null) return "—";
  const m = Math.floor(secs / 60);
  const s = Math.round(secs % 60);
  return m ? `${m}m ${s}s` : `${s}s`;
}

const CHECK_MARK = { pass: "✓", fail: "✕", warn: "△", na: "·" };

function CheckRow({ check }) {
  return (
    <div className="flex items-center gap-2 py-0.5 text-xs">
      <span
        className={`w-3 text-center font-semibold ${
          check.status === "fail" ? "text-gray-900" : "text-gray-500"
        }`}
      >
        {CHECK_MARK[check.status]}
      </span>
      <span
        className={
          check.status === "fail"
            ? "font-medium text-gray-900"
            : check.status === "na"
            ? "text-gray-400"
            : "text-gray-600"
        }
      >
        {check.label}
      </span>
      {!check.critical && (
        <span className="text-[10px] uppercase tracking-wide text-gray-300">
          non-critical
        </span>
      )}
    </div>
  );
}

function ExpandedRow({ record, colSpan }) {
  const checks = record.eval?.checks ?? [];
  const transcript = record.transcript ?? [];
  return (
    <tr className="bg-gray-50/70">
      <td colSpan={colSpan} className="px-4 py-4">
        <div className="grid gap-6 lg:grid-cols-2">
          <div>
            <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-gray-500">
              Evaluation · {record.eval?.passed}/{record.eval?.total} checks
            </h4>
            <div className="rounded border border-gray-200 bg-white px-3 py-2">
              {checks.map((c) => (
                <CheckRow key={c.name} check={c} />
              ))}
            </div>
          </div>

          <div>
            <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-gray-500">
              Transcript · {transcript.length} turns
            </h4>
            <div className="max-h-60 space-y-1.5 overflow-y-auto rounded border border-gray-200 bg-white px-3 py-2">
              {transcript.length === 0 && (
                <p className="text-xs text-gray-400">No transcript captured.</p>
              )}
              {transcript.map((t, i) => {
                const isAction = /^\[action:/.test(t.content || "");
                return (
                  <div key={i} className="text-xs leading-relaxed">
                    <span className="mr-2 inline-block w-16 shrink-0 align-top font-mono text-[10px] uppercase tracking-wide text-gray-400">
                      {t.role === "assistant" ? "Agent" : "Driver"}
                    </span>
                    <span
                      className={
                        isAction
                          ? "font-mono text-[11px] text-gray-500"
                          : "text-gray-800"
                      }
                    >
                      {t.content}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </td>
    </tr>
  );
}

const COLUMNS = [
  "Completed",
  "Load",
  "Carrier",
  "Sentiment",
  "ETA",
  "Risk",
  "Alert",
  "Turns",
  "Duration",
  "LLM TTFB",
  "Eval",
  "",
];

export default function RecordsTable({ records }) {
  const [open, setOpen] = useState(null);

  if (!records || records.length === 0) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white py-16 text-center text-sm text-gray-400">
        No call records yet. Place a call from the Inbound Loads tab.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
      <table className="min-w-full divide-y divide-gray-200 text-sm">
        <thead className="bg-gray-50">
          <tr>
            {COLUMNS.map((c, i) => (
              <th
                key={i}
                className="whitespace-nowrap px-3 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wide text-gray-500"
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {records.map((r) => {
            const isOpen = open === r.call_id;
            return (
              <Fragment key={r.call_id}>
                <tr
                  onClick={() => setOpen(isOpen ? null : r.call_id)}
                  className={`cursor-pointer hover:bg-gray-50 ${
                    isOpen ? "bg-gray-50" : ""
                  }`}
                >
                  <td className="whitespace-nowrap px-3 py-2.5 text-gray-600">
                    {fmtTime(r.completed_at)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs font-medium text-gray-900">
                    {r.load_id || "—"}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-gray-700">
                    {r.carrier || "—"}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 capitalize text-gray-700">
                    {r.driver_sentiment || "—"}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 font-mono tabular-nums text-gray-700">
                    {r.eta_minutes != null ? `${r.eta_minutes}m` : "—"}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5">
                    <RiskMeter score={r.risk_score} level={r.risk_level} />
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-gray-700">
                    {r.logistics_alerted ? "Escalated" : "—"}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 font-mono tabular-nums text-gray-600">
                    {r.num_turns ?? "—"}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 font-mono tabular-nums text-gray-600">
                    {fmtDuration(r.duration_secs)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 font-mono tabular-nums text-gray-600">
                    {r.llm_ttfb_mean_ms != null ? `${Math.round(r.llm_ttfb_mean_ms)}ms` : "—"}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5">
                    <EvalBadge verdict={r.eval?.verdict} score={r.eval?.score} />
                  </td>
                  <td className="px-3 py-2.5 text-gray-400">{isOpen ? "▾" : "▸"}</td>
                </tr>
                {isOpen && (
                  <ExpandedRow record={r} colSpan={COLUMNS.length} />
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
