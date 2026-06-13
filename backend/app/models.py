from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


class RouteGeometry(BaseModel):
    type: str = "LineString"
    coordinates: List[List[float]]  # [[lon, lat] or [lon, lat, elev]]


class AnalysisOptions(BaseModel):
    steep_threshold_deg: float = 30.0
    max_data_age_days: int = 7


class AnalyseRequest(BaseModel):
    route: RouteGeometry
    options: Optional[AnalysisOptions] = None
    selected_dataset_date: Optional[str] = None


class SegmentResult(BaseModel):
    index: int
    lat: float
    lon: float
    fsc_pct: Optional[int] = None
    slope_deg: float
    risk_class: str
    acquisition_date: str


class Summary(BaseModel):
    safety_indicator: str
    snow_covered_pct: float
    high_risk_snow_pct: float
    cloud_obscured_pct: float
    data_age_days: Dict[str, Any]


class CopernicusTrace(BaseModel):
    mode: str
    queried_s3_keys: List[str]
    used_s3_keys: List[str]
    downloaded_s3_keys: List[str]


class DatasetDateGroup(BaseModel):
    date: str
    products: List[str]


class RouteDatasetOptionsResponse(BaseModel):
    dates: List[DatasetDateGroup]
    latest_date: Optional[str] = None
    tiles: List[str]


class AnalysisResponse(BaseModel):
    summary: Summary
    segments: List[SegmentResult]
    copernicus_trace: Optional[CopernicusTrace] = None
    warnings: List[str] = Field(default_factory=list)
