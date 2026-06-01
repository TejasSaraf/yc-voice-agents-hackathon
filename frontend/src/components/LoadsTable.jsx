import { Fragment, useState } from "react";
import RiskMeter from "./RiskMeter.jsx";

const STAGE_LABEL = {
  eta_confirmed: "ETA confirmed",
  cargo_verified: "Cargo verified",
  dock_assigned: "Dock assigned",
  risk_assessed: "Risk assessed",
  alerted: "Escalated",
  completed: "Completed",
};

function StatusCell({ live }) {
  if (!live || !live.stage) {
    return <span className="text-gray-400">Idle</span>;
  }
  const active = live.stage !== "completed";
  return (
    <span className="inline-flex items-center gap-1.5 text-gray-700">
      {active && (
        <span className="pulse-dot h-1.5 w-1.5 rounded-full bg-gray-800" />
      )}
      {STAGE_LABEL[live.stage] || live.stage}
    </span>
  );
}

function Detail({ label, value }) {
  if (value == null || value === "") return null;
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wide text-gray-400">{label}</dt>
      <dd className="text-xs text-gray-800">{value}</dd>
    </div>
  );
}

function LiveDetail({ live, colSpan }) {
  return (
    <tr className="bg-gray-50/70">
      <td colSpan={colSpan} className="px-4 py-4">
        <dl className="grid grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-4">
          <Detail label="Location" value={live.current_location} />
          <Detail label="ETA" value={live.eta_text} />
          <Detail label="Sentiment" value={live.driver_sentiment} />
          <Detail label="Dock / Gate" value={live.dock ? `${live.dock} · ${live.gate || "—"}` : null} />
          <Detail
            label="Live risk"
            value={live.live_risk ? `${live.live_risk.score} ${live.live_risk.level}` : null}
          />
          <Detail label="Escalated" value={live.logistics_alerted ? "Yes" : "No"} />
          {live.alert_action && (
            <div className="col-span-2 sm:col-span-4">
              <dt className="text-[10px] uppercase tracking-wide text-gray-400">
                Recommended action
              </dt>
              <dd className="text-xs text-gray-700">{live.alert_action}</dd>
            </div>
          )}
        </dl>
      </td>
    </tr>
  );
}

const COLUMNS = ["Load", "Carrier", "Commodity", "Lane", "Appt", "Risk", "Status", ""];

function HackathonToast({ pos }) {
  if (!pos) return null;
  return (
    <div
      className="pointer-events-none fixed z-[9999]"
      style={{ left: pos.x, top: pos.y, transform: "translateY(-100%)" }}
    >
      <div className="max-w-[min(220px,calc(100vw-1rem))] rounded-lg border border-orange-200 bg-orange-50 px-3 py-2 text-xs leading-relaxed text-orange-800 shadow-lg">
        <span className="font-semibold">Nemotron models</span> were live during the hackathon — now disabled
      </div>
      {/* arrow pointing down on the right side toward the button */}
      <div className="absolute right-3 top-full border-4 border-transparent border-t-orange-200" />
    </div>
  );
}

export default function LoadsTable({ shipments, onCall, callingId }) {
  const [open, setOpen] = useState(null);
  const [toastPos, setToastPos] = useState(null);

  const handleMouseEnter = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    setToastPos({ x: rect.left, y: rect.top - 10 });
  };

  return (
    <>
    <HackathonToast pos={toastPos} />
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
          {shipments.map((s) => {
            const hasLive = Boolean(s.live_call && s.live_call.stage);
            const isOpen = open === s.load_id;
            return (
              <Fragment key={s.load_id}>
                <tr className={`hover:bg-gray-50 ${isOpen ? "bg-gray-50" : ""}`}>
                  <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs font-medium text-gray-900">
                    {s.load_id}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-gray-700">{s.carrier}</td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-gray-700">{s.commodity}</td>
                  <td className="px-3 py-2.5 text-gray-500">{s.origin}</td>
                  <td className="whitespace-nowrap px-3 py-2.5 font-mono tabular-nums text-gray-700">
                    {s.appointment}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5">
                    <RiskMeter score={s.risk?.score} level={s.risk?.level} />
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5">
                    <StatusCell live={s.live_call} />
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-right">
                    <div className="flex items-center justify-end gap-2">
                      {hasLive && (
                        <button
                          onClick={() => setOpen(isOpen ? null : s.load_id)}
                          className="rounded px-1.5 py-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
                          title="Call details"
                        >
                          {isOpen ? "▾" : "▸"}
                        </button>
                      )}
                      <button
                        onClick={() => onCall(s)}
                        disabled={callingId === s.load_id}
                        onMouseEnter={handleMouseEnter}
                        onMouseLeave={() => setToastPos(null)}
                        className="rounded-md border border-gray-300 bg-white px-3 py-1 text-xs font-semibold text-gray-800 hover:bg-gray-900 hover:text-white disabled:opacity-40"
                        title="Place an outbound AI call to this carrier"
                      >
                        {callingId === s.load_id ? "Calling…" : "Call carrier"}
                      </button>
                    </div>
                  </td>
                </tr>
                {isOpen && hasLive && (
                  <LiveDetail live={s.live_call} colSpan={COLUMNS.length} />
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
    </>
  );
}
