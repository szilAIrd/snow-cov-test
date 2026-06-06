import { SegmentResult } from "../types";

const RISK_LABEL: Record<string, string> = {
  clear: "No snow",
  snow_low_risk: "Snow – low risk",
  snow_high_risk: "Snow – HIGH RISK",
  cloud_obscured: "Cloud / no data",
  water: "Water",
};

interface Props {
  segments: SegmentResult[];
}

// Show every Nth segment to keep the table manageable
function decimated(arr: SegmentResult[], max = 200): SegmentResult[] {
  if (arr.length <= max) return arr;
  const step = Math.ceil(arr.length / max);
  return arr.filter((_, i) => i % step === 0);
}

export function SegmentTable({ segments }: Props) {
  const rows = decimated(segments);

  return (
    <div className="segment-panel">
      <h3>
        Per-segment detail ({segments.length} points
        {rows.length < segments.length ? `, showing every ${Math.ceil(segments.length / rows.length)}th` : ""})
      </h3>
      <table className="segment-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Lat</th>
            <th>Lon</th>
            <th>FSC</th>
            <th>Slope</th>
            <th>Classification</th>
            <th>Data date</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.index}>
              <td>{s.index}</td>
              <td>{s.lat.toFixed(4)}</td>
              <td>{s.lon.toFixed(4)}</td>
              <td>{s.fsc_pct != null ? `${s.fsc_pct}%` : "—"}</td>
              <td>{s.slope_deg}°</td>
              <td>
                <span className={`risk-badge ${s.risk_class}`}>
                  {RISK_LABEL[s.risk_class] ?? s.risk_class}
                </span>
              </td>
              <td>{s.acquisition_date}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
