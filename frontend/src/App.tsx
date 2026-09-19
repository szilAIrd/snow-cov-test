import { useEffect, useState, type KeyboardEvent } from "react";
import { DayPicker } from "react-day-picker";
import "react-day-picker/style.css";
import {
  AnalysisResponse,
  CopernicusRunHistoryItem,
  CopernicusTrace,
  RouteDatasetOptionsResponse,
} from "./types";
import { MapView, fscToColor } from "./components/MapView";
import { GPXUpload } from "./components/GPXUpload";
import { SummaryCard } from "./components/SummaryCard";
import { SegmentTable } from "./components/SegmentTable";
import { CopernicusTracePanel } from "./components/CopernicusTracePanel";

interface FscInfo {
  available: boolean;
  file_count: number;
  date: string | null;
  lon_min: number | null;
  lat_min: number | null;
  lon_max: number | null;
  lat_max: number | null;
}

interface SearchResult {
  place_id: number;
  display_name: string;
  lat: string;
  lon: string;
  type?: string;
}

interface MapSearchTarget {
  lat: number;
  lon: number;
  label: string;
  token: number;
}

const NON_SNOW_LEGEND = [
  { color: "#22c55e", label: "No snow detected" },
  { color: "#96A0AA", label: "Cloud / no data" },
  { color: "#1e40af", label: "Water" },
];

// Gradient stops for the FSC legend bar (0% → 100%)
const FSC_STOPS = [0, 25, 50, 75, 100];

// Sentinel stored in availableDateCache for months where the server is in mock
// mode. Lets us skip re-fetching while still keeping all dates selectable.
const MOCK_SENTINEL = "__mock__";

/** Returns YYYY-MM-DD for N days ago */
function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().split("T")[0];
}

function fromIsoDate(isoDate: string): Date {
  return new Date(`${isoDate}T12:00:00`);
}

export default function App() {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [fscInfo, setFscInfo] = useState<FscInfo | null>(null);
  const [tracePanelOpen, setTracePanelOpen] = useState(true);
  const [traceHistory, setTraceHistory] = useState<CopernicusRunHistoryItem[]>([]);
  const [showSegmentDetail, setShowSegmentDetail] = useState(true);
  const [datasetOptions, setDatasetOptions] = useState<RouteDatasetOptionsResponse | null>(null);
  const [selectedDatasetDate, setSelectedDatasetDate] = useState<string | null>(null);
  const [expandedDatasetDates, setExpandedDatasetDates] = useState<string[]>([]);
  const [loadingDatasetOptions, setLoadingDatasetOptions] = useState(false);
  const [analysisWarnings, setAnalysisWarnings] = useState<string[]>([]);

  // Layer visibility state
  const [showOsmLayer, setShowOsmLayer] = useState(true);
  const [showSnowLayer, setShowSnowLayer] = useState(true);
  const [snowLayerDate, setSnowLayerDate] = useState(daysAgo(1));
  const [snowLayerOpacity, setSnowLayerOpacity] = useState(0.85);

  // Available-dates calendar state
  const [routeCenter, setRouteCenter] = useState<{ lat: number; lon: number } | null>(null);
  const [availableDateCache, setAvailableDateCache] = useState<Map<string, Set<string>>>(new Map());
  const [calendarMonth, setCalendarMonth] = useState<Date>(new Date());
  const [loadingDates, setLoadingDates] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [mapSearchTarget, setMapSearchTarget] = useState<MapSearchTarget | null>(null);

  // Fetch FSC dataset info on mount; use the real acquisition date if available
  useEffect(() => {
    fetch("/api/v1/fsc/info")
      .then((r) => r.json())
      .then((info: FscInfo) => {
        setFscInfo(info);
        if (info.available && info.date) {
          setSnowLayerDate(info.date);
        }
      })
      .catch(() => {}); // non-fatal — fall back to yesterday
  }, []);

  // ── Header location search (OpenStreetMap Nominatim) ──────────────────
  useEffect(() => {
    const q = searchQuery.trim();
    if (q.length < 2) {
      setSearchResults([]);
      setSearchOpen(false);
      setSearchLoading(false);
      setSearchError(null);
      return;
    }

    const t = setTimeout(async () => {
      setSearchLoading(true);
      setSearchError(null);
      try {
        const url =
          "https://nominatim.openstreetmap.org/search?format=jsonv2&limit=8&q=" +
          encodeURIComponent(q);
        const res = await fetch(url, {
          headers: { "Accept-Language": "en" },
        });
        if (!res.ok) {
          throw new Error(`Search request failed (${res.status})`);
        }
        const json = (await res.json()) as SearchResult[];
        setSearchResults(json);
        setSearchOpen(true);
      } catch (err) {
        setSearchResults([]);
        setSearchOpen(true);
        setSearchError(err instanceof Error ? err.message : "Search failed");
      } finally {
        setSearchLoading(false);
      }
    }, 250);

    return () => clearTimeout(t);
  }, [searchQuery]);

  const selectSearchResult = (r: SearchResult) => {
    const lat = Number(r.lat);
    const lon = Number(r.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;

    setMapSearchTarget({
      lat,
      lon,
      label: r.display_name,
      token: Date.now(),
    });
    setSearchQuery(r.display_name);
    setSearchOpen(false);
  };

  const handleSearchKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      if (searchResults.length > 0) {
        selectSearchResult(searchResults[0]);
      }
    }
    if (e.key === "Escape") {
      setSearchOpen(false);
    }
  };

  // ── Date-availability helpers ───────────────────────────────────────────
  const toIsoDate = (d: Date): string => {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  };

  const routeDatasetDates = datasetOptions?.dates.map((group) => group.date) ?? [];
  const routeDatasetDateSet = new Set(routeDatasetDates);
  const hasRouteDatasetDates = routeDatasetDateSet.size > 0;

  const setAnalysisDate = (dateIso: string) => {
    setSelectedDatasetDate(dateIso);
    setSnowLayerDate(dateIso);
    setCalendarMonth(fromIsoDate(dateIso));
    if (routeDatasetDateSet.has(dateIso)) {
      setExpandedDatasetDates((prev) => (prev.includes(dateIso) ? prev : [dateIso, ...prev]));
    }
  };

  const isDateDisabled = (d: Date): boolean => {
    const isoDate = toIsoDate(d);
    if (hasRouteDatasetDates) {
      return !routeDatasetDateSet.has(isoDate);
    }
    if (!routeCenter) return false;
    const mk = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    const monthDates = availableDateCache.get(mk);
    if (!monthDates || monthDates.has(MOCK_SENTINEL)) return false; // not fetched or mock
    return !monthDates.has(isoDate);
  };

  const isDateAvailable = (d: Date): boolean => {
    const isoDate = toIsoDate(d);
    if (hasRouteDatasetDates) {
      return routeDatasetDateSet.has(isoDate);
    }
    const mk = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    const monthDates = availableDateCache.get(mk);
    if (!monthDates || monthDates.has(MOCK_SENTINEL)) return false;
    return monthDates.has(isoDate);
  };

  const fetchAvailableDatesForCenter = async (
    center: { lat: number; lon: number },
    month: Date
  ) => {
    const mk = `${month.getFullYear()}-${String(month.getMonth() + 1).padStart(2, "0")}`;
    if (availableDateCache.has(mk)) return;
    setLoadingDates(true);
    try {
      const res = await fetch(
        `/api/v1/fsc/available-dates?lat=${center.lat}&lon=${center.lon}` +
          `&year=${month.getFullYear()}&month=${month.getMonth() + 1}`
      );
      if (res.ok) {
        const json = (await res.json()) as { dates: string[]; mode?: string };
        // In mock mode cache a sentinel so we don't re-fetch on every navigation,
        // but isDateDisabled will still treat the month as "no filter applied".
        const toCache = json.mode === "mock" ? [MOCK_SENTINEL] : json.dates;
        setAvailableDateCache((prev) => new Map(prev).set(mk, new Set(toCache)));
      }
    } catch {
      // non-fatal — calendar shows all dates as selectable
    } finally {
      setLoadingDates(false);
    }
  };

  const handleMonthChange = (month: Date) => {
    setCalendarMonth(month);
    if (routeCenter) fetchAvailableDatesForCenter(routeCenter, month);
  };

  const toggleDatasetDateExpanded = (d: string) => {
    setExpandedDatasetDates((prev) =>
      prev.includes(d) ? prev.filter((v) => v !== d) : [...prev, d]
    );
  };

  const fetchRouteDatasetOptions = async (nextFile: File) => {
    setLoadingDatasetOptions(true);
    setDatasetOptions(null);
    setSelectedDatasetDate(null);
    setExpandedDatasetDates([]);
    setAnalysisWarnings([]);

    try {
      const form = new FormData();
      form.append("file", nextFile);

      const res = await fetch("/api/v1/datasets/gpx", {
        method: "POST",
        body: form,
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `Server error ${res.status}`);
      }

      const options = (await res.json()) as RouteDatasetOptionsResponse;
      setDatasetOptions(options);
      if (options.latest_date) {
        setExpandedDatasetDates([options.latest_date]);
        setSelectedDatasetDate(options.latest_date);
        setSnowLayerDate(options.latest_date);
        setCalendarMonth(fromIsoDate(options.latest_date));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load datasets for this GPX");
    } finally {
      setLoadingDatasetOptions(false);
    }
  };

  const handleFile = (f: File) => {
    setFile(f);
    setError(null);
    setAnalysis(null);
    fetchRouteDatasetOptions(f);
  };

  const exportTraceHistory = () => {
    if (traceHistory.length === 0) return;
    const payload = {
      exported_at: new Date().toISOString(),
      run_count: traceHistory.length,
      runs: traceHistory,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `copernicus-trace-${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  const handleAnalyse = async () => {
    if (!file) return;
    setLoading(true);
    setError(null);
    setAnalysisWarnings([]);

    try {
      const form = new FormData();
      form.append("file", file);

      const datasetDateToUse = selectedDatasetDate ?? datasetOptions?.latest_date ?? null;
      const query = datasetDateToUse
        ? `?selected_dataset_date=${encodeURIComponent(datasetDateToUse)}`
        : "";

      const res = await fetch(`/api/v1/analyse/gpx${query}`, {
        method: "POST",
        body: form,
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `Server error ${res.status}`);
      }

      const data: AnalysisResponse = await res.json();
      setAnalysis(data);
        setAnalysisWarnings(data.warnings ?? []);

      const trace: CopernicusTrace =
        data.copernicus_trace ??
        {
          mode: "mock",
          queried_s3_keys: [],
          used_s3_keys: [],
          downloaded_s3_keys: [],
        };
      setTraceHistory((prev) => [
        {
          run_id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          run_at: new Date().toISOString(),
          source_file: file.name,
          safety_indicator: data.summary.safety_indicator,
          trace,
        },
        ...prev,
      ]);

      if (data.segments.length > 0) {
        const mid = data.segments[Math.floor(data.segments.length / 2)];
        const center = { lat: mid.lat, lon: mid.lon };
        setRouteCenter(center);
        fetchAvailableDatesForCenter(center, calendarMonth);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  };

  const currentMonthKey = `${calendarMonth.getFullYear()}-${String(calendarMonth.getMonth() + 1).padStart(2, "0")}`;
  const currentMonthDates = availableDateCache.get(currentMonthKey);
  const noDataThisMonth =
    !!routeCenter &&
    !loadingDates &&
    !!currentMonthDates &&
    !currentMonthDates.has(MOCK_SENTINEL) &&
    currentMonthDates.size === 0;
  const activeAnalysisDate = selectedDatasetDate ?? datasetOptions?.latest_date ?? null;

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-title-wrap">
          <h1>SnowRoute</h1>
          <span>Mountain Snow Conditions</span>
        </div>
        <div className="header-search">
          <input
            type="text"
            className="header-search-input"
            placeholder="Search city, mountain, place..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onFocus={() => {
              if (searchResults.length > 0 || searchError || searchLoading) {
                setSearchOpen(true);
              }
            }}
            onBlur={() => window.setTimeout(() => setSearchOpen(false), 120)}
            onKeyDown={handleSearchKeyDown}
          />
          {searchOpen && (
            <div className="header-search-dropdown">
              {searchLoading && <div className="search-item search-item-muted">Searching...</div>}
              {!searchLoading && searchError && (
                <div className="search-item search-item-muted">{searchError}</div>
              )}
              {!searchLoading && !searchError && searchResults.length === 0 && (
                <div className="search-item search-item-muted">No results</div>
              )}
              {!searchLoading && !searchError && searchResults.map((r) => (
                <button
                  key={r.place_id}
                  type="button"
                  className="search-item"
                  onClick={() => selectSearchResult(r)}
                >
                  {r.display_name}
                </button>
              ))}
            </div>
          )}
        </div>
      </header>

      <div className="app-body">
        {/* ── Sidebar ─────────────────────────────────────── */}
        <aside className="sidebar">
          <GPXUpload onFile={handleFile} loading={loading} />

          {file && (
            <div className="dataset-picker-card">
              <div className="dataset-picker-header">
                <h3>Available Copernicus Datasets</h3>
                {loadingDatasetOptions && <span className="dataset-picker-loading">Loading...</span>}
              </div>
              {datasetOptions?.tiles && datasetOptions.tiles.length > 0 && (
                <p className="dataset-picker-tiles">Route tiles: {datasetOptions.tiles.join(", ")}</p>
              )}
              {!loadingDatasetOptions && datasetOptions && datasetOptions.dates.length > 0 && (
                <>
                  <p className="dataset-picker-help">
                    Choose a date below or in the calendar. Both stay in sync and the selected date is
                    used for analysis.
                  </p>
                  {activeAnalysisDate && (
                    <p className="dataset-picker-selection">
                      Analysis will use <strong>{activeAnalysisDate}</strong>.
                    </p>
                  )}
                </>
              )}
              {!loadingDatasetOptions && datasetOptions && datasetOptions.dates.length === 0 && (
                <p className="dataset-picker-empty">No intersecting datasets found in the lookback window.</p>
              )}
              {!loadingDatasetOptions && datasetOptions && datasetOptions.dates.length > 0 && (
                <div className="dataset-date-table">
                  {datasetOptions.dates.map((group) => {
                    const isExpanded = expandedDatasetDates.includes(group.date);
                    const isSelected = selectedDatasetDate === group.date;
                    const isLatest = datasetOptions.latest_date === group.date;
                    return (
                      <div
                        key={group.date}
                        className={`dataset-date-row${isSelected ? " selected" : ""}${isLatest ? " default" : ""}`}
                      >
                        <button
                          type="button"
                          className="dataset-date-main"
                          onClick={() => setAnalysisDate(group.date)}
                        >
                          <span>{group.date}</span>
                          {isSelected && <span className="dataset-chip">selected</span>}
                          {isLatest && <span className="dataset-chip dataset-chip-default">latest</span>}
                        </button>
                        <button
                          type="button"
                          className="dataset-expand-btn"
                          onClick={() => toggleDatasetDateExpanded(group.date)}
                        >
                          {isExpanded ? "Hide products" : `Show products (${group.products.length})`}
                        </button>
                        {isExpanded && (
                          <ul className="dataset-product-list">
                            {group.products.map((productKey) => (
                              <li key={productKey}>{productKey}</li>
                            ))}
                          </ul>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {error && <div className="error-box">{error}</div>}
          {analysisWarnings.map((warning) => (
            <div key={warning} className="warning-box">{warning}</div>
          ))}

          <button
            className="btn-analyse"
            onClick={handleAnalyse}
            disabled={!file || loading || loadingDatasetOptions}
          >
            {loading
              ? "Analysing…"
              : loadingDatasetOptions
                ? "Loading Datasets…"
                : "Analyse Snow Conditions"}
          </button>

          {analysis && (
            <button
              className="btn-secondary"
              type="button"
              onClick={() => setShowSegmentDetail((v) => !v)}
            >
              {showSegmentDetail ? "Hide Per-segment Detail" : "Show Per-segment Detail"}
            </button>
          )}

          <CopernicusTracePanel
            isOpen={tracePanelOpen}
            onToggle={() => setTracePanelOpen((v) => !v)}
            onExport={exportTraceHistory}
            runs={traceHistory}
          />

          {analysis && <SummaryCard summary={analysis.summary} />}

          {/* Base map toggle */}
          <div className="layer-card layer-card--compact">
            <div className="layer-card-header">
              <h3>OpenStreetMap</h3>
              <label className="layer-toggle">
                <input
                  type="checkbox"
                  checked={showOsmLayer}
                  onChange={(e) => setShowOsmLayer(e.target.checked)}
                />
                <span>{showOsmLayer ? "On" : "Off"}</span>
              </label>
            </div>
          </div>

          {/* Snow coverage layer controls */}
          <div className="layer-card">
            <div className="layer-card-header">
              <h3>FSC Snow Cover</h3>
              {fscInfo?.available && (
                <span className="real-data-badge">
                  {fscInfo.file_count} real tile{fscInfo.file_count !== 1 ? "s" : ""}
                </span>
              )}
              <label className="layer-toggle">
                <input
                  type="checkbox"
                  checked={showSnowLayer}
                  onChange={(e) => setShowSnowLayer(e.target.checked)}
                />
                <span>{showSnowLayer ? "On" : "Off"}</span>
              </label>
            </div>
            {showSnowLayer && (
              <>
                <div className="layer-row">
                  <label>
                    Analysis date{loadingDates && <span className="dates-loading"> · loading…</span>}
                  </label>
                  <div className="date-picker-wrap">
                    <DayPicker
                      mode="single"
                      selected={
                        (activeAnalysisDate ?? snowLayerDate)
                          ? fromIsoDate(activeAnalysisDate ?? snowLayerDate)
                          : undefined
                      }
                      onSelect={(d) => {
                        if (!d) return;
                        const isoDate = toIsoDate(d);
                        if (hasRouteDatasetDates) {
                          setAnalysisDate(isoDate);
                          return;
                        }
                        setSnowLayerDate(isoDate);
                      }}
                      month={calendarMonth}
                      onMonthChange={handleMonthChange}
                      disabled={[isDateDisabled, { after: new Date() }]}
                      modifiers={{ available: isDateAvailable }}
                      modifiersClassNames={{ available: "rdp-day-available" }}
                    />
                    {noDataThisMonth && (
                      <p className="dates-empty">No Copernicus data this month</p>
                    )}
                  </div>
                </div>
                <div className="layer-row">
                  <label htmlFor="snow-opacity">
                    Opacity <strong>{Math.round(snowLayerOpacity * 100)}%</strong>
                  </label>
                  <input
                    id="snow-opacity"
                    type="range"
                    min="0.1"
                    max="1"
                    step="0.05"
                    value={snowLayerOpacity}
                    onChange={(e) => setSnowLayerOpacity(parseFloat(e.target.value))}
                  />
                </div>
                <p className="layer-source">
                  {fscInfo?.available
                    ? `Copernicus CLMS · HR-WSI FSCOG · ${fscInfo.date ?? snowLayerDate}`
                    : "Copernicus CLMS · HR-WSI FSCOG (synthetic model)"}
                </p>
              </>
            )}
          </div>

          {/* Legend */}
          <div className="legend">
            <h3>Map legend</h3>

            {/* FSC gradient scale */}
            <div className="legend-section-label">Snow cover (FSC %)</div>
            <div className="fsc-gradient-bar"
              style={{
                background: `linear-gradient(to right, ${FSC_STOPS.map(
                  (v) => fscToColor(v)
                ).join(", ")})`,
              }}
            />
            <div className="fsc-gradient-labels">
              <span>0 % (low)</span>
              <span>100 % (dense)</span>
            </div>
            <div className="legend-item fsc-risk-note">
              <span className="legend-ring" />Steep ≥30° → red border
            </div>

            {/* Non-snow entries */}
            <div className="legend-divider" />
            <div className="legend-items">
              {NON_SNOW_LEGEND.map(({ color, label }) => (
                <div className="legend-item" key={label}>
                  <div className="legend-dot" style={{ background: color }} />
                  {label}
                </div>
              ))}
            </div>
          </div>
        </aside>

        {/* ── Map + table ──────────────────────────────────── */}
        <div className="map-wrap">
          <MapView
            analysis={analysis}
            showOsmLayer={showOsmLayer}
            showSnowLayer={showSnowLayer}
            snowLayerDate={snowLayerDate}
            snowLayerOpacity={snowLayerOpacity}
            searchTarget={mapSearchTarget}
          />
          {analysis && showSegmentDetail && <SegmentTable segments={analysis.segments} />}
        </div>
      </div>
    </div>
  );
}
