export type RiskClass =
  | "clear"
  | "snow_low_risk"
  | "snow_high_risk"
  | "cloud_obscured"
  | "water";

export type SafetyIndicator = "GREEN" | "AMBER" | "RED";

export interface SegmentResult {
  index: number;
  lat: number;
  lon: number;
  fsc_pct: number | null;
  slope_deg: number;
  risk_class: RiskClass;
  acquisition_date: string;
}

export interface DataAge {
  min: number;
  max: number;
  mean: number;
}

export interface Summary {
  safety_indicator: SafetyIndicator;
  snow_covered_pct: number;
  high_risk_snow_pct: number;
  cloud_obscured_pct: number;
  data_age_days: DataAge;
}

export interface CopernicusTrace {
  mode: "real_data" | "mock";
  queried_s3_keys: string[];
  used_s3_keys: string[];
  downloaded_s3_keys: string[];
}

export interface CopernicusRunHistoryItem {
  run_id: string;
  run_at: string;
  source_file: string;
  safety_indicator: SafetyIndicator;
  trace: CopernicusTrace;
}

export interface AnalysisResponse {
  summary: Summary;
  segments: SegmentResult[];
  copernicus_trace?: CopernicusTrace;
}
