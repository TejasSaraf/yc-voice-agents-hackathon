const LEVEL_CONFIG = {
  CRITICAL: {
    bg: "bg-red-50",
    border: "border-red-200",
    text: "text-red-600",
    dot: "bg-red-500",
    bar: "bg-red-500",
    label: "CRITICAL",
  },
  WARNING: {
    bg: "bg-amber-50",
    border: "border-amber-200",
    text: "text-amber-600",
    dot: "bg-amber-500",
    bar: "bg-amber-500",
    label: "WARNING",
  },
  MONITOR: {
    bg: "bg-emerald-50",
    border: "border-emerald-200",
    text: "text-emerald-600",
    dot: "bg-emerald-500",
    bar: "bg-emerald-500",
    label: "MONITOR",
  },
};

export function RiskBadge({ level, score, size = "md" }) {
  const cfg = LEVEL_CONFIG[level] ?? LEVEL_CONFIG.MONITOR;

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-semibold tracking-wide text-xs
        ${cfg.bg} ${cfg.border} ${cfg.text}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${cfg.dot} ${level === "CRITICAL" ? "pulse-dot" : ""}`} />
      {cfg.label}
      {score !== undefined && (
        <span className="ml-0.5 opacity-60">{score}</span>
      )}
    </span>
  );
}

export function RiskScoreBar({ score, level }) {
  const cfg = LEVEL_CONFIG[level] ?? LEVEL_CONFIG.MONITOR;
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-gray-200">
        <div
          className={`h-full rounded-full transition-all duration-700 ${cfg.bar}`}
          style={{ width: `${score}%` }}
        />
      </div>
      <span className={`text-xs font-bold tabular-nums ${cfg.text}`}>{score}</span>
    </div>
  );
}

export function getLevelConfig(level) {
  return LEVEL_CONFIG[level] ?? LEVEL_CONFIG.MONITOR;
}
