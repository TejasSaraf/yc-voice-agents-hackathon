import { RiskBadge } from "./RiskBadge.jsx";
import LiveCallStrip from "./LiveCallStrip.jsx";

function PhoneRing() {
  return (
    <div className="relative flex h-20 w-20 items-center justify-center">
      {[1, 2, 3].map((i) => (
        <span
          key={i}
          className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-15"
          style={{ animationDelay: `${i * 300}ms`, animationDuration: "1.5s" }}
        />
      ))}
      <span className="relative text-4xl">📞</span>
    </div>
  );
}

function SignalRow({ label, contribution, weight }) {
  const pct = Math.round((contribution / (weight ?? 1)) * 100);
  return (
    <div className="flex items-center gap-3 text-xs">
      <span className="w-32 shrink-0 text-gray-500">{label}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-gray-100">
        <div
          className="h-full rounded-full bg-blue-400 transition-all duration-700"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-10 text-right font-mono text-gray-600">
        +{contribution.toFixed(3)}
      </span>
    </div>
  );
}

export default function CallModal({ callResult, shipment, onClose }) {
  const isDemo = callResult?.status === "demo";
  const risk = shipment?.risk;
  const liveCall = shipment?.live_call;

  // Phase is driven by real call state, not fake timers:
  //   ringing   — call placed, no live update has landed yet
  //   active    — bot is mid-call, tools are firing
  //   completed — end_call fired (stage "completed" or completed_at set)
  const isCompleted =
    liveCall?.stage === "completed" || Boolean(liveCall?.completed_at);
  const phase = isCompleted
    ? "completed"
    : liveCall?.stage
    ? "active"
    : "ringing";

  const PHASE = {
    ringing:   { icon: "📞", label: "Connecting to driver…", sub: "text-gray-800" },
    active:    { icon: "🔊", label: "Call in progress",       sub: "text-blue-700" },
    completed: { icon: "✅", label: "Call completed",         sub: "text-emerald-700" },
  }[phase];

  const baselineScore = risk?.baseline_score ?? risk?.score ?? 0;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center sm:items-center"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-gray-900/30 backdrop-blur-sm" onClick={onClose} />

      {/* Panel */}
      <div className="slide-up relative z-10 max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-t-2xl sm:rounded-2xl border border-gray-200 bg-white shadow-2xl">
        {/* Close */}
        <button
          onClick={onClose}
          className="absolute right-4 top-4 z-10 rounded-full p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
        >
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>

        {/* Header */}
        <div className="border-b border-gray-100 px-6 py-5">
          <p className="text-xs font-semibold uppercase tracking-widest text-gray-400">
            Outbound Call
          </p>
          <p className="mt-0.5 text-lg font-bold text-gray-900">
            {shipment?.driver_name} · {shipment?.carrier}
          </p>
          <p className="text-sm text-gray-500">
            {shipment?.commodity} → {shipment?.dock}, {shipment?.appointment}
          </p>
        </div>

        {/* Call status */}
        <div className="flex flex-col items-center gap-4 px-6 py-8">
          {phase === "ringing" ? (
            <PhoneRing />
          ) : (
            <span className="text-5xl">{PHASE.icon}</span>
          )}

          <div className="text-center">
            <p className={`text-lg font-semibold ${PHASE.sub}`}>{PHASE.label}</p>
            {callResult?.to && (
              <p className="mt-1 font-mono text-sm text-gray-400">{callResult.to}</p>
            )}
            {callResult?.call_sid && (
              <p className="mt-0.5 font-mono text-xs text-gray-300">{callResult.call_sid}</p>
            )}
          </div>

          {/* Demo mode notice */}
          {isDemo && (
            <div className="w-full rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
              <p className="font-semibold">Demo mode</p>
              <p className="mt-0.5 text-xs text-amber-600">
                Set <code className="rounded bg-amber-100 px-1">TWILIO_ACCOUNT_SID</code>,{" "}
                <code className="rounded bg-amber-100 px-1">TWILIO_AUTH_TOKEN</code>, and{" "}
                <code className="rounded bg-amber-100 px-1">TWILIO_PHONE_NUMBER</code> in{" "}
                <code className="rounded bg-amber-100 px-1">server/.env</code> to place real calls.
              </p>
            </div>
          )}
        </div>

        {/* Live call updates — appears as soon as the first tool fires, and
            shows the final picture once the call completes. */}
        {liveCall?.stage && (
          <LiveCallStrip liveCall={liveCall} baselineScore={baselineScore} />
        )}

        {/* Risk score breakdown — pre-call snapshot before any live data, then
            the live/post-call score once the call is underway. */}
        {risk && (
          <div className="border-t border-gray-100 px-6 py-5">
            <div className="mb-3 flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-widest text-gray-400">
                {risk.source === "live"
                  ? isCompleted
                    ? "Post-call risk"
                    : "Live risk"
                  : "Pre-call risk snapshot"}
              </p>
              <RiskBadge level={risk.level} score={risk.score} />
            </div>

            <div className="space-y-2">
              {risk.signals &&
                Object.entries(risk.signals).map(([key, sig]) => (
                  <SignalRow
                    key={key}
                    label={key.replace(/_/g, " ")}
                    contribution={sig.contribution}
                    weight={sig.weight}
                  />
                ))}
            </div>

            {risk.source !== "live" && (
              <div className="mt-3 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-500">
                <span className="font-medium text-gray-700">Baseline only.</span>{" "}
                Score updates in real-time as the driver responds — voice sentiment is captured during
                the live call.
              </div>
            )}
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-3 border-t border-gray-100 px-6 py-4">
          <button
            onClick={onClose}
            className={`flex-1 rounded-lg px-4 py-2.5 text-sm font-semibold transition-colors
              ${isCompleted
                ? "bg-emerald-500 text-white hover:bg-emerald-600"
                : "border border-gray-200 bg-gray-50 text-gray-600 hover:bg-gray-100"
              }`}
          >
            {isCompleted ? "Done" : "Close"}
          </button>
        </div>
      </div>
    </div>
  );
}
