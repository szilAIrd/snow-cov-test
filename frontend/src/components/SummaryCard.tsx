import { Summary } from "../types";

const INDICATOR_DESC: Record<string, string> = {
  GREEN: "Route looks passable",
  AMBER: "Proceed with caution",
  RED: "High risk or insufficient data",
};

interface Props {
  summary: Summary;
}

export function SummaryCard({ summary }: Props) {
  const ind = summary.safety_indicator;
  const age = summary.data_age_days;

  return (
    <div className="summary-card">
      <h2>Snow Analysis</h2>

      <div className="indicator">
        <div className={`indicator-dot ${ind}`} />
        <div>
          <div className={`indicator-label ${ind}`}>{ind}</div>
          <div className="indicator-sub">{INDICATOR_DESC[ind]}</div>
        </div>
      </div>

      <div className="stats-grid">
        <div className="stat-item">
          <div className="stat-value">{summary.snow_covered_pct}%</div>
          <div className="stat-label">Snow-covered</div>
        </div>
        <div className="stat-item">
          <div className="stat-value">{summary.high_risk_snow_pct}%</div>
          <div className="stat-label">Steep snow ≥ 30°</div>
        </div>
        <div className="stat-item">
          <div className="stat-value">{summary.cloud_obscured_pct}%</div>
          <div className="stat-label">Cloud / no data</div>
        </div>
        <div className="stat-item">
          <div className="stat-value">{age.mean}d</div>
          <div className="stat-label">Avg data age</div>
        </div>
      </div>

      <div className="data-age-row">
        Data: {age.min}–{age.max} days old
        {age.max >= 5 && (
          <span className="data-age-warn">
            {" "}— Warning: data may be stale
          </span>
        )}
      </div>
    </div>
  );
}
