export default function RiskMeter({ score, level }) {
  const s = typeof score === "number" ? score : null;
  const filled = s == null ? 0 : Math.round((s / 100) * 5);
  return (
    <div className="flex items-center gap-2">
      <div className="flex gap-0.5" aria-hidden>
        {[0, 1, 2, 3, 4].map((i) => (
          <span
            key={i}
            className={`h-3 w-1.5 rounded-[1px] ${
              i < filled ? "bg-gray-900" : "bg-gray-200"
            }`}
          />
        ))}
      </div>
      <span className="font-mono text-sm tabular-nums text-gray-900">
        {s == null ? "—" : s}
      </span>
      {level && (
        <span className="text-[10px] font-medium uppercase tracking-wide text-gray-400">
          {level}
        </span>
      )}
    </div>
  );
}
