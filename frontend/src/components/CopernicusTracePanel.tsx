import { CopernicusRunHistoryItem } from "../types";

interface Props {
  isOpen: boolean;
  onToggle: () => void;
  onExport: () => void;
  runs: CopernicusRunHistoryItem[];
}

function runTitle(run: CopernicusRunHistoryItem): string {
  const ts = new Date(run.run_at).toLocaleString();
  return `${ts} · ${run.source_file} · ${run.safety_indicator}`;
}

function KeyList({ keys }: { keys: string[] }) {
  if (keys.length === 0) {
    return <div className="trace-empty">None</div>;
  }
  return (
    <ul className="trace-key-list">
      {keys.map((k) => (
        <li key={k} title={k}>
          {k}
        </li>
      ))}
    </ul>
  );
}

export function CopernicusTracePanel({ isOpen, onToggle, onExport, runs }: Props) {
  return (
    <div className="trace-panel">
      <div className="trace-panel-header">
        <h3>Copernicus S3 Trace</h3>
        <div className="trace-panel-actions">
          <button type="button" className="trace-btn" onClick={onToggle}>
            {isOpen ? "Hide" : "Show"}
          </button>
          <button
            type="button"
            className="trace-btn"
            onClick={onExport}
            disabled={runs.length === 0}
          >
            Export
          </button>
        </div>
      </div>

      {isOpen && (
        <div className="trace-panel-body">
          {runs.length === 0 && <p className="trace-empty">No analyses yet.</p>}

          {runs.map((run) => (
            <details key={run.run_id} className="trace-run" open={runs.length === 1}>
              <summary>{runTitle(run)}</summary>
              {run.trace.mode === "mock" ? (
                <p className="trace-empty">Mock mode: no Copernicus S3 data queried.</p>
              ) : (
                <>
                  <div className="trace-section-title">Queried packages</div>
                  <KeyList keys={run.trace.queried_s3_keys} />

                  <div className="trace-section-title">Used in analysis</div>
                  <KeyList keys={run.trace.used_s3_keys} />

                  <div className="trace-section-title">Downloaded from S3</div>
                  <KeyList keys={run.trace.downloaded_s3_keys} />
                </>
              )}
            </details>
          ))}
        </div>
      )}
    </div>
  );
}
