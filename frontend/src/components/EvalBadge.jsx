const STYLES = {
  PASS: { box: "border border-gray-300 text-gray-700", mark: "✓" },
  WARN: { box: "border border-gray-400 bg-gray-100 text-gray-900", mark: "△" },
  FAIL: { box: "bg-gray-900 text-white", mark: "✕" },
};

export default function EvalBadge({ verdict, score, compact = false }) {
  const v = STYLES[verdict] || STYLES.WARN;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-semibold ${v.box}`}
    >
      <span aria-hidden>{v.mark}</span>
      {verdict || "—"}
      {!compact && typeof score === "number" && (
        <span className="font-mono tabular-nums opacity-70">{score}</span>
      )}
    </span>
  );
}
