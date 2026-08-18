import { useEffect, useState } from "react";
import { api } from "./api";
import KpiCards from "./components/KpiCards";
import RiskRadar from "./components/RiskRadar";
import AnomalyDetail from "./components/AnomalyDetail";
import ForecastChart from "./components/ForecastChart";
import BriefPanel from "./components/BriefPanel";

export default function App() {
  const [kpis, setKpis] = useState(null);
  const [anomalies, setAnomalies] = useState(null);
  const [forecast, setForecast] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [loadError, setLoadError] = useState(null);

  useEffect(() => {
    Promise.all([api.getKpis(), api.getAnomalies(), api.getForecast()])
      .then(([k, a, f]) => {
        setKpis(k);
        setAnomalies(a.items);
        setForecast(f);
        if (a.items.length) setSelectedId(a.items[0].id);
      })
      .catch((err) => {
        setLoadError(
          "Could not reach the Fiscal Sentinel API. Is the backend running on " +
            (import.meta.env.VITE_API_URL || "http://localhost:8000") +
            "?"
        );
        console.error(err);
      });
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    api
      .getAnomalyDetail(selectedId)
      .then(setDetail)
      .catch((err) => console.error(err));
  }, [selectedId]);

  if (loadError) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6">
        <div className="max-w-md text-center">
          <h1 className="text-lg font-semibold text-[var(--text-primary)] mb-2">
            Fiscal Sentinel
          </h1>
          <p className="text-sm text-[var(--text-secondary)]">{loadError}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-[var(--border-hairline)] bg-[var(--surface-card)]">
        <div className="max-w-7xl mx-auto px-6 py-4">
          <h1 className="text-lg font-semibold text-[var(--text-primary)]">
            Fiscal Sentinel
          </h1>
          <p className="text-sm text-[var(--text-secondary)]">
            Most systems tell councils what happened. Fiscal Sentinel tells them what
            needs attention next.
          </p>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-6 flex flex-col gap-5">
        <KpiCards kpis={kpis} />

        <div className="grid grid-cols-1 lg:grid-cols-5 gap-5 min-h-0">
          <div className="lg:col-span-2 min-h-[420px] lg:min-h-[560px]">
            {anomalies ? (
              <RiskRadar items={anomalies} selectedId={selectedId} onSelect={setSelectedId} />
            ) : (
              <SkeletonCard />
            )}
          </div>
          <div className="lg:col-span-3">
            {anomalies ? <AnomalyDetail detail={detail} /> : <SkeletonCard />}
          </div>
        </div>

        {forecast ? <ForecastChart forecast={forecast} /> : <SkeletonCard />}

        <BriefPanel />
      </main>

      <footer className="max-w-7xl mx-auto px-6 py-6 text-xs text-[var(--text-muted)]">
        Fiscal Sentinel is a decision-support demo. Flagged items are financial
        anomalies and potential revenue leakage requiring verification, not findings
        of wrongdoing.
      </footer>
    </div>
  );
}

function SkeletonCard() {
  return (
    <div className="rounded-lg border border-[var(--border-hairline)] bg-[var(--surface-card)] h-full min-h-[200px] animate-pulse" />
  );
}
