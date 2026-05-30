const SENTIMENT_STYLES = {
  confident:  { bg: "bg-emerald-50",  border: "border-emerald-200",  text: "text-emerald-700",  icon: "💪" },
  calm:       { bg: "bg-sky-50",      border: "border-sky-200",      text: "text-sky-700",      icon: "🙂" },
  uncertain:  { bg: "bg-amber-50",    border: "border-amber-200",    text: "text-amber-700",    icon: "😕" },
  frustrated: { bg: "bg-red-50",      border: "border-red-200",      text: "text-red-700",      icon: "😤" },
};

const STAGE_LABELS = {
  eta_confirmed:  "ETA captured",
  cargo_verified: "Cargo verified",
  dock_assigned:  "Dock assigned",
  risk_assessed:  "Risk re-scored",
  alerted:        "Logistics alerted",
  completed:      "Call completed",
};

function relativeTime(iso) {
  if (!iso) return "";
  const ms = Date.now() - new Date(iso).getTime();
  const s  = Math.floor(ms / 1000);
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  return `${h}h ago`;
}

function SentimentChip({ sentiment }) {
  if (!sentiment) return null;
  const s = SENTIMENT_STYLES[sentiment] ?? SENTIMENT_STYLES.calm;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold capitalize
        ${s.bg} ${s.border} ${s.text}`}
    >
      <span>{s.icon}</span>
      {sentiment}
    </span>
  );
}

export default function LiveCallStrip({ liveCall, baselineScore }) {
  if (!liveCall || !liveCall.stage) return null;

  const {
    stage,
    current_location,
    eta_text,
    eta_minutes_from_now,
    driver_sentiment,
    cargo_ok,
    cargo_problems,
    dock_notified,
    logistics_alerted,
    alert_action,
    live_risk,
    last_update,
    completed_at,
  } = liveCall;

  const isActive   = stage !== "completed";
  const isAlerted  = logistics_alerted === true;
  const newScore   = live_risk?.score;
  const delta      = (newScore != null && baselineScore != null)
    ? newScore - baselineScore
    : null;

  return (
    <div className="border-t border-gray-100">
      {/* Header strip */}
      <div className={`flex items-center justify-between px-4 py-2
        ${isActive ? "bg-blue-50" : "bg-gray-50"}`}>
        <div className="flex items-center gap-2">
          <span className={`relative flex h-2 w-2`}>
            {isActive && (
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-400 opacity-75" />
            )}
            <span className={`relative inline-flex h-2 w-2 rounded-full
              ${isActive ? "bg-blue-500" : "bg-gray-400"}`} />
          </span>
          <span className={`text-xs font-bold uppercase tracking-widest
            ${isActive ? "text-blue-700" : "text-gray-500"}`}>
            {isActive ? "Live call" : "Last call"}
          </span>
          <span className="text-xs text-gray-400">·</span>
          <span className="text-xs text-gray-500">{STAGE_LABELS[stage] ?? stage}</span>
        </div>
        <span className="text-xs text-gray-400">
          {relativeTime(completed_at || last_update)}
        </span>
      </div>

      {/* Body */}
      <div className="space-y-2 px-4 py-3">

        {/* Driver said */}
        {(eta_text || driver_sentiment) && (
          <div className="flex flex-wrap items-center gap-2">
            <SentimentChip sentiment={driver_sentiment} />
            {eta_text && (
              <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-700">
                <span className="text-gray-400">said:</span> "{eta_text}"
                {eta_minutes_from_now != null && (
                  <span className="ml-1 text-gray-500">
                    (≈{eta_minutes_from_now}m)
                  </span>
                )}
              </span>
            )}
          </div>
        )}

        {/* Location */}
        {current_location && (
          <div className="text-xs text-gray-500">
            <span className="text-gray-400">Location:</span>{" "}
            <span className="text-gray-700">{current_location}</span>
          </div>
        )}

        {/* Cargo + dock badges */}
        {(cargo_ok !== undefined || dock_notified) && (
          <div className="flex flex-wrap gap-1.5">
            {cargo_ok === true && (
              <span className="rounded border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">
                ✓ Cargo OK
              </span>
            )}
            {cargo_ok === false && (
              <span className="rounded border border-red-200 bg-red-50 px-2 py-0.5 text-xs text-red-700">
                ✗ Cargo issue
                {cargo_problems && Array.isArray(cargo_problems) && (
                  <span className="ml-1 text-red-600/70">
                    ({cargo_problems.join(", ")})
                  </span>
                )}
              </span>
            )}
            {dock_notified && (
              <span className="rounded border border-sky-200 bg-sky-50 px-2 py-0.5 text-xs text-sky-700">
                ✓ Dock prepped
              </span>
            )}
          </div>
        )}

        {/* Updated risk delta */}
        {newScore != null && delta != null && (
          <div className="flex items-center justify-between rounded-lg border border-gray-200 bg-white px-3 py-2">
            <div className="text-xs text-gray-500">
              <div>Risk: <span className="font-bold text-gray-900">{baselineScore} → {newScore}</span></div>
              <div className="text-[10px] text-gray-400">baseline → post-call</div>
            </div>
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-bold tabular-nums
                ${delta > 0
                  ? "bg-red-100 text-red-700"
                  : delta < 0
                  ? "bg-emerald-100 text-emerald-700"
                  : "bg-gray-100 text-gray-600"
                }`}
            >
              {delta > 0 ? "+" : ""}{delta}
            </span>
          </div>
        )}

        {/* Logistics alert */}
        {isAlerted && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs">
            <div className="font-semibold text-red-700">🚨 Logistics team alerted</div>
            {alert_action && (
              <div className="mt-0.5 text-red-600/80">{alert_action}</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
