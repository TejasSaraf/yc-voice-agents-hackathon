import { useCallback, useEffect, useRef, useState } from "react";
import LoadsTable from "./components/LoadsTable.jsx";
import RecordsTable from "./components/RecordsTable.jsx";

function useClock() {
  const [time, setTime] = useState(new Date());
  useEffect(() => {
    const id = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return time;
}

function Kpi({ label, value, sub }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-4 py-3">
      <p className="text-[11px] font-medium uppercase tracking-wide text-gray-400">
        {label}
      </p>
      <p className="mt-1 font-mono text-2xl tabular-nums text-gray-900">{value}</p>
      {sub && <p className="text-xs text-gray-400">{sub}</p>}
    </div>
  );
}

export default function Dashboard() {
  const [fleet, setFleet] = useState(null);
  const [records, setRecords] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("loads");
  const [query, setQuery] = useState("");
  const [callingId, setCallingId] = useState(null);
  const time = useClock();
  const pollRef = useRef(null);

  const refresh = useCallback(async () => {
    try {
      const [f, r] = await Promise.all([
        fetch("/api/fleet").then((res) => {
          if (!res.ok) throw new Error(`fleet ${res.status}`);
          return res.json();
        }),
        fetch("/api/records").then((res) => (res.ok ? res.json() : { records: [] })),
      ]);
      setFleet(f);
      setRecords(r);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    pollRef.current = setInterval(refresh, 1_000);
    return () => clearInterval(pollRef.current);
  }, [refresh]);

  const handleCall = useCallback(async (shipment) => {
    setCallingId(shipment.load_id);
    try {
      await fetch("/api/calls/trigger", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ load_id: shipment.load_id, scenario: "carrier" }),
      });
    } catch {
      void 0;
    } finally {
      setTimeout(() => setCallingId(null), 1500);
    }
  }, []);

  const shipments = fleet?.shipments ?? [];
  const recordRows = records?.records ?? [];

  const q = query.trim().toLowerCase();
  const matches = (parts) => !q || parts.filter(Boolean).some((p) => String(p).toLowerCase().includes(q));
  const visibleLoads = shipments.filter((s) => matches([s.load_id, s.carrier, s.commodity, s.origin]));
  const visibleRecords = recordRows.filter((r) =>
    matches([r.load_id, r.carrier, r.commodity, r.driver_sentiment])
  );

  const atRisk = shipments.filter((s) => ["WARNING", "CRITICAL"].includes(s.risk?.level)).length;
  const activeCalls = shipments.filter(
    (s) => s.live_call?.stage && s.live_call.stage !== "completed"
  ).length;
  const evalSummary = records?.summary;

  return (
    <div className="min-h-screen bg-gray-50 text-gray-900">
      <header className="sticky top-0 z-20 border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-screen-2xl items-center justify-between px-6 py-3">
          <a href="#/" className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded bg-gray-900 font-bold text-white">
              FV
            </div>
            <div>
              <h1 className="text-sm font-semibold leading-tight text-gray-900">
                FreightVoice
              </h1>
              <p className="text-[11px] text-gray-400">Outbound AI Calls · Inbound Logistics</p>
            </div>
          </a>
          <div className="flex items-center gap-5 text-gray-500">
            <a href="#/" className="hidden text-xs font-medium text-gray-500 hover:text-gray-900 sm:block">
              ← Home
            </a>
            <span className="hidden items-center gap-1.5 sm:flex">
              <span className="pulse-dot h-1.5 w-1.5 rounded-full bg-gray-800" />
              <span className="text-xs">Live</span>
            </span>
            <span className="font-mono text-xs tabular-nums">
              {time.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
            </span>
            <button
              onClick={refresh}
              className="rounded border border-gray-300 px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-100"
            >
              Refresh
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-screen-2xl space-y-5 px-6 py-6">
        {error && (
          <div className="rounded-lg border border-gray-300 bg-gray-100 px-4 py-2.5 text-sm text-gray-700">
            <span className="font-semibold">Connection error:</span> {error}{" "}
            <button onClick={refresh} className="underline">retry</button>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Kpi label="Inbound loads" value={shipments.length} />
          <Kpi label="At-risk" value={atRisk} sub="Warning + Critical" />
          <Kpi label="Active calls" value={activeCalls} />
          <Kpi
            label="Eval pass rate"
            value={evalSummary ? `${evalSummary.pass_rate}%` : "—"}
            sub={evalSummary ? `${evalSummary.passed}/${evalSummary.total} calls` : "no calls yet"}
          />
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="inline-flex rounded-lg border border-gray-200 bg-white p-0.5">
            {[
              { key: "loads", label: `Inbound Loads · ${shipments.length}` },
              { key: "records", label: `Call Records · ${recordRows.length}` },
            ].map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={`rounded-md px-3 py-1.5 text-xs font-semibold transition-colors ${
                  tab === t.key
                    ? "bg-gray-900 text-white"
                    : "text-gray-500 hover:text-gray-800"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter by load, carrier, commodity…"
            className="w-64 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs text-gray-700 placeholder:text-gray-400 focus:border-gray-500 focus:outline-none"
          />
        </div>

        {loading && !fleet ? (
          <div className="h-64 animate-pulse rounded-lg border border-gray-200 bg-white" />
        ) : tab === "loads" ? (
          <LoadsTable shipments={visibleLoads} onCall={handleCall} callingId={callingId} />
        ) : (
          <RecordsTable records={visibleRecords} />
        )}

        <p className="pb-4 text-center text-[11px] text-gray-300">
          FreightVoice · Outbound AI carrier calls · local eval scoring
          {fleet?.as_of && <> · updated {new Date(fleet.as_of).toLocaleTimeString()}</>}
        </p>
      </main>
    </div>
  );
}
