# SnowRoute — MVP

Mountain snow conditions tool built from the DesignDoc. Analyses a GPX route against simulated FSC (Fractional Snow Cover) data and classifies each point as clear, snow-low-risk, snow-high-risk, cloud-obscured, or water based on the algorithm in §9.2 of the design document.

## Architecture

```
frontend/   React + MapLibre GL JS (Vite)
backend/    Python / FastAPI
```

The FSC provider (`backend/app/fsc_provider.py`) now uses Copernicus HR-WSI data only (real S3 products). When no product is available for a point/area, the API marks it as cloud/no-data (no synthetic fallback).

---

## One-click start

For the normal user path, run one of these from the repo root:

```bash
npm start
```

Or on macOS, double-click the launcher file:

```text
Start SnowRoute.command
```

This starts the full Docker stack, waits for the API health check, and opens the app at http://localhost.

---

## Advanced local development

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
# API available at http://localhost:8000
# Swagger UI at http://localhost:8000/docs
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# App available at http://localhost:5173
```

Vite proxies `/api/*` to `http://localhost:8000`, so no CORS configuration is needed during development.

---

## Docker Compose (manual)

```bash
docker compose up --build
# App available at http://localhost:80
# API available at http://localhost:8000
```

If you change Dockerfiles or `frontend/nginx.conf`, run with `--build` once so containers pick up the new image layers.

The frontend Nginx config allows request bodies up to 20 MB (`client_max_body_size 20m`), which is suitable for larger GPX uploads.

---

## Using the app

1. Open the app in your browser.
2. Drop a `.gpx` file onto the upload area (or click to browse).
3. Click **Analyse Snow Conditions**.
4. The map shows each route point coloured by risk class; the sidebar shows the summary card (GREEN / AMBER / RED) and per-segment stats.
5. Use the **Copernicus S3 Trace** sidebar panel to review history for the current browser session:
  - queried package keys
  - packages used in analysis
  - packages downloaded from S3
  - export the session trace as JSON

---

## API reference

### `POST /api/v1/analyse/gpx`

Upload a GPX file as multipart form data.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `file` | File | — | `.gpx` file |
| `steep_threshold_deg` | float | 30 | Slope threshold for high-risk classification |
| `max_data_age_days` | int | 7 | Discard FSC observations older than this |
| `selected_dataset_date` | string (YYYY-MM-DD) | latest available route date | Force analysis to use only this acquisition date |

### `POST /api/v1/datasets/gpx`

Upload a GPX file as multipart form data and get route-intersecting Copernicus Sentinel dataset options grouped by date.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `file` | File | — | `.gpx` file |
| `lookback_days` | int | 30 | How many days back to search in Copernicus S3 |

Response format:

```json
{
  "latest_date": "2026-04-02",
  "tiles": ["32TLR", "32TMR"],
  "dates": [
    {
      "date": "2026-04-02",
      "products": [
        "GFSC/32TLR/2026/04/02/CLMS_WSI_FSC_020m_T32TLR_20260402T102841_S2A_V200/...tif"
      ]
    }
  ]
}
```

### `POST /api/v1/analyse`

Send a GeoJSON LineString body:

```json
{
  "route": {
    "type": "LineString",
    "coordinates": [[lon, lat], ...]
  },
  "options": {
    "steep_threshold_deg": 30,
    "max_data_age_days": 7
  }
}
```

---

## MVP scope (DesignDoc §16.3)

| Item | Status |
|---|---|
| Alpine region FSC data ingestion (real Copernicus S3) | ✅ |
| Route analysis API — GPX upload | ✅ |
| Web app with map view and summary card | ✅ |
| Slope risk classification | ✅ |
| Temporal gap-fill (7-day window) | ✅ |
| Mobile app | Phase 2 |
| Draw-on-map route input | Phase 2 |
| Weather forecast integration | Phase 2 |
| Community reports | Phase 3 |
| Live CLMS HDA API ingestion | In use via Copernicus S3 provider |
