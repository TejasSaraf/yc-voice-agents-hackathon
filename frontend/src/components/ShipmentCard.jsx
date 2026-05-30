import { RiskBadge, RiskScoreBar, getLevelConfig } from "./RiskBadge.jsx";
import LiveCallStrip from "./LiveCallStrip.jsx";

function IconTruck() {
  return (
    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M8 17h8m-8 0a2 2 0 11-4 0 2 2 0 014 0zm8 0a2 2 0 114 0 2 2 0 01-4 0zM3 7h2l2-4h10l2 4h2v7H3V7z" />
    </svg>
  );
}
function IconThermometer() {
  return (
    <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 9V3m0 6a3 3 0 110 6 3 3 0 010-6zm0 6v3" />
    </svg>
  );
}
function IconPhone() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.948V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" />
    </svg>
  );
}
function IconFactory() {
  return (
    <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0H5m14 0h2M5 21H3m4-10h2m4 0h2m-8 4h2m4 0h2" />
    </svg>
  );
}
function IconAlert() {
  return (
    <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
    </svg>
  );
}

function formatCost(usd) {
  if (usd >= 1_000_000) return `$${(usd / 1_000_000).toFixed(1)}M/hr`;
  return `$${(usd / 1_000).toFixed(0)}K/hr`;
}

export default function ShipmentCard({ shipment, onCall, calling }) {
  const { risk, live_call } = shipment;
  const level    = risk?.level ?? "MONITOR";
  const score    = risk?.score ?? 0;
  const isLive   = risk?.source === "live";
  const baselineScore = risk?.baseline_score ?? score;
  const cfg = getLevelConfig(level);

  const borderAccent =
    level === "CRITICAL"
      ? "border-l-red-500"
      : level === "WARNING"
      ? "border-l-amber-400"
      : "border-l-emerald-500";

  return (
    <div
      className={`fade-in flex flex-col rounded-xl border border-gray-200 border-l-2 ${borderAccent}
        bg-white shadow-sm transition-shadow duration-150 hover:shadow-md`}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2 px-4 pt-4 pb-2">
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 font-mono text-xs font-semibold tracking-wider text-gray-400">
            {shipment.load_id}
            {isLive && (
              <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 px-1.5 py-0.5 text-[9px] font-bold text-blue-700">
                <span className="pulse-dot h-1 w-1 rounded-full bg-blue-500" />
                LIVE
              </span>
            )}
          </p>
          <p className="mt-0.5 truncate text-sm font-semibold text-gray-900">
            {shipment.commodity}
          </p>
        </div>
        <RiskBadge level={level} score={score} />
      </div>

      {/* Risk bar */}
      <div className="px-4 pb-3">
        <RiskScoreBar score={score} level={level} />
      </div>

      {/* Body */}
      <div className="flex-1 space-y-2.5 border-t border-gray-100 px-4 py-3">
        {/* Shipper + carrier */}
        <div className="flex items-start gap-2 text-xs text-gray-500">
          <IconTruck />
          <div className="min-w-0">
            <p className="font-medium text-gray-700">{shipment.shipper}</p>
            <p className="text-gray-400">
              {shipment.carrier} · <span className="text-gray-500">{shipment.driver_name}</span>
            </p>
          </div>
        </div>

        {/* Route */}
        <div className="text-xs text-gray-400">
          <span className="text-gray-500">{shipment.origin}</span>
          <span className="mx-1.5 text-gray-300">→</span>
          <span className="font-medium text-gray-700">
            {shipment.dock}, {shipment.gate}
          </span>
          <span className="ml-2 rounded bg-gray-100 px-1.5 py-0.5 font-mono font-semibold text-gray-600">
            {shipment.appointment}
          </span>
        </div>

        {/* Production line */}
        <div className="flex items-center gap-1.5 text-xs text-gray-400">
          <IconFactory />
          <span className="truncate">{shipment.production_line}</span>
        </div>

        {/* Flags row */}
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="rounded border border-gray-200 bg-gray-50 px-1.5 py-0.5 text-xs text-gray-500">
            {Math.round(shipment.lane_on_time_rate * 100)}% OTD
          </span>

          <span className="rounded border border-rose-100 bg-rose-50 px-1.5 py-0.5 text-xs text-rose-600">
            {formatCost(shipment.hourly_downtime_cost)}
          </span>

          {shipment.requires_temp_control && (
            <span className="flex items-center gap-1 rounded border border-blue-100 bg-blue-50 px-1.5 py-0.5 text-xs text-blue-600">
              <IconThermometer />
              {shipment.temp_range}
            </span>
          )}

          {shipment.weather_description && (
            <span className="flex items-center gap-1 rounded border border-amber-100 bg-amber-50 px-1.5 py-0.5 text-xs text-amber-600">
              <IconAlert />
              weather
            </span>
          )}
        </div>
      </div>

      {/* Signal breakdown */}
      {risk?.signals && (
        <div className="border-t border-gray-100 px-4 py-2.5">
          <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-widest text-gray-300">
            Risk signals
          </p>
          <div className="space-y-1">
            {Object.entries(risk.signals).map(([key, sig]) => (
              <div key={key} className="flex items-center gap-1.5">
                <div className="h-1 flex-1 overflow-hidden rounded-full bg-gray-100">
                  <div
                    className={`h-full rounded-full ${cfg.bar}`}
                    style={{ width: `${Math.round((sig.contribution / (sig.weight ?? 1)) * 100)}%` }}
                  />
                </div>
                <span className="w-24 truncate text-right text-[10px] text-gray-400">
                  {sig.label}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Live call updates (renders nothing if no call in progress) */}
      <LiveCallStrip liveCall={live_call} baselineScore={baselineScore} />

      {/* Footer — Call button */}
      <div className="border-t border-gray-100 px-4 py-3">
        <button
          onClick={() => onCall(shipment)}
          disabled={calling}
          className={`flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold
            transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-offset-1
            ${
              level === "CRITICAL"
                ? "bg-red-500 hover:bg-red-600 focus:ring-red-400 text-white shadow-sm"
                : level === "WARNING"
                ? "bg-amber-500 hover:bg-amber-600 focus:ring-amber-400 text-white shadow-sm"
                : "bg-gray-100 hover:bg-gray-200 focus:ring-gray-300 text-gray-700"
            }
            disabled:cursor-not-allowed disabled:opacity-50`}
        >
          {calling ? (
            <>
              <span className="spin inline-block h-4 w-4 rounded-full border-2 border-current border-t-transparent" />
              Initiating…
            </>
          ) : (
            <>
              <IconPhone />
              Call {shipment.driver_name}
            </>
          )}
        </button>
      </div>
    </div>
  );
}
