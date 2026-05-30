function StatCard({ label, value, sub, accent }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white px-5 py-4 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-widest text-gray-400">{label}</p>
      <p className={`mt-1 text-3xl font-bold tabular-nums ${accent ?? "text-gray-900"}`}>
        {value}
      </p>
      {sub && <p className="mt-0.5 text-xs text-gray-400">{sub}</p>}
    </div>
  );
}

function formatExposure(usd) {
  if (usd >= 1_000_000) return `$${(usd / 1_000_000).toFixed(1)}M`;
  return `$${(usd / 1_000).toFixed(0)}K`;
}

export default function FleetStats({ summary }) {
  if (!summary) {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[...Array(4)].map((_, i) => (
          <div
            key={i}
            className="h-24 animate-pulse rounded-xl border border-gray-200 bg-white"
          />
        ))}
      </div>
    );
  }

  const { counts, total_inbound, hourly_downtime_exposure_usd } = summary;

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <StatCard
        label="Total Inbound"
        value={total_inbound}
        sub="loads today"
      />
      <StatCard
        label="Critical"
        value={counts.high ?? 0}
        sub="immediate action needed"
        accent="text-red-500"
      />
      <StatCard
        label="Warning"
        value={counts.medium ?? 0}
        sub="monitoring elevated"
        accent="text-amber-500"
      />
      <StatCard
        label="Downtime Exposure"
        value={formatExposure(hourly_downtime_exposure_usd)}
        sub="per hour behind flagged loads"
        accent="text-rose-500"
      />
    </div>
  );
}
