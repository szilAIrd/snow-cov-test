# SnowRoute — Mountain Snow Conditions Tool
## Software Design Document

**Version:** 0.1 (Draft)
**Date:** 2026-05-25
**Status:** Draft for Review

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Goals and Non-Goals](#3-goals-and-non-goals)
4. [User Personas](#4-user-personas)
5. [Functional Requirements](#5-functional-requirements)
6. [Non-Functional Requirements](#6-non-functional-requirements)
7. [Data Sources](#7-data-sources)
8. [System Architecture](#8-system-architecture)
9. [Component Design](#9-component-design)
10. [Data Pipeline](#10-data-pipeline)
11. [User Interface Design](#11-user-interface-design)
12. [API Design](#12-api-design)
13. [Key Challenges and Mitigations](#13-key-challenges-and-mitigations)
14. [Security and Privacy](#14-security-and-privacy)
15. [Testing Strategy](#15-testing-strategy)
16. [Deployment and Infrastructure](#16-deployment-and-infrastructure)
17. [Open Questions](#17-open-questions)

---

## 1. Executive Summary

**SnowRoute** is a web and mobile application that helps mountain users (hikers, trekkers, trail runners, mountaineers) assess snow conditions along a specific route *before* setting out. It fuses daily-aggregated satellite-derived snow products — primarily Copernicus Land Monitoring Service (CLMS) Fractional Snow Cover (FSC) data — with auxiliary sources such as weather forecasts, webcams, and crowd-sourced reports, and presents the result as a clear, actionable per-route snow analysis.

The tool answers the fundamental question a mountain user has when planning:
> *"Will there be snow on my route tomorrow, and is it dangerous?"*

---

## 2. Problem Statement

### 2.1 The Planning Gap

Planning a mountain hike or multi-day trek — especially early in the season (April–July in the northern hemisphere) or late season (September–October) — is hampered by a lack of spatially precise, current snow information:

- **Avalanche bulletins** cover broad zones and focus on danger rating, not route-level passability.
- **Weather forecasts** predict new snowfall but do not reflect existing snow coverage at route level.
- **Webcams** provide near-real-time visual data but cover only a tiny fraction of mountain terrain, clustered around ski resorts and mountain huts. Large sections of trails between huts have zero webcam coverage.
- **Mountain guides and alpine clubs** publish seasonal route reports, but these are updated infrequently and require local knowledge to interpret.
- **Satellite imagery** (e.g., Google Maps terrain view) is static and does not reflect seasonal conditions.

### 2.2 Consequences

- Hikers encounter unexpected snow fields, increasing risk of slipping on steep terrain.
- Routes planned without crampons or ice axe require unplanned retreat, wasting effort and posing danger.
- Snow on steep sections is disproportionately dangerous relative to snow on flat terrain — steepness information is rarely combined with snow coverage in existing tools.
- In group scenarios (guided tours, competitions), incorrect snow assessment creates liability issues.

### 2.3 Opportunity

Processed satellite imagery from the Copernicus programme provides Fractional Snow Cover (FSC) data with:
- **20 m spatial resolution** (Sentinel-2 optical)
- **1–2 day revisit time** per pixel (variable with cloud cover)
- **Daily updated** products (CLMS near-real-time delivery, typically within 24 h of acquisition)
- **Global coverage** of land surfaces

This data is freely available and already distinguishes snow-covered (with percentage), snow-free, cloud-obscured, and water-body pixels. Combined with a Digital Elevation Model (DEM) for terrain slope, it is possible to provide per-route, slope-aware snow coverage analysis that no existing consumer tool delivers.

---

## 3. Goals and Non-Goals

### 3.1 Goals

| ID  | Goal |
|-----|------|
| G1  | Provide up-to-date (daily aggregated) snow conditions along any user-supplied or drawn route |
| G2  | Highlight snow on steep terrain separately from snow on flat terrain as a safety indicator |
| G3  | Cover all mountain areas globally where Copernicus/Sentinel-2 data is available |
| G4  | Support route input via GPX file upload and interactive map drawing |
| G5  | Deliver the product as a web application and a native mobile application |
| G6  | Provide a clear, non-technical output understandable by general mountain users |
| G7  | Integrate auxiliary data (webcams, weather forecast, user reports) to fill gaps in satellite coverage caused by cloud cover |

### 3.2 Non-Goals

| ID  | Non-Goal |
|-----|----------|
| NG1 | Real-time avalanche path prediction or avalanche danger rating (separate specialist domain) |
| NG2 | Turn-by-turn navigation or route guidance |
| NG3 | Snow depth measurement (FSC provides coverage %, not depth) |
| NG4 | Sub-hourly data refresh (Sentinel-2 revisit is 1–5 days per location) |
| NG5 | Road or ski piste snow conditions (different use case) |

---

## 4. User Personas

### Persona A — The Weekend Hiker
- Age 30–50, hikes 1–2 times per month in spring/summer/autumn
- Plans routes at home 1–3 days in advance using smartphone or laptop
- Not a specialist; unfamiliar with FSC, NDSI, or satellite data concepts
- Needs: simple traffic-light snow status per route, clear safety warnings

### Persona B — The Multi-Day Trekker
- Age 25–45, plans long-distance treks (e.g., Tour du Mont Blanc, Alta Via)
- Spends significant effort researching conditions days to weeks before departure
- Comfortable reading maps; wants actual data, not just summaries
- Needs: day-by-day snow forecast along the full route, pass-level detail, integration with GPX from trip planner

### Persona C — The Trail Runner
- Age 25–40, competes or trains in alpine environments
- Primarily concerned with whether a trail is runnable or requires YakTrax/microspikes
- Time-poor; needs a fast, mobile-friendly answer
- Needs: quick binary "runnable / requires traction device / avoid" assessment

### Persona D — The Mountain Guide / Trip Organiser
- Professional or semi-professional, responsible for group safety
- Wants exportable reports, source data visibility, and confidence scores
- Needs: data provenance, cloud-cover gaps flagged, ability to share PDF/link report with clients

---

## 5. Functional Requirements

### 5.1 Route Input

| ID   | Requirement |
|------|-------------|
| FR-1 | Users can upload a GPX file (tracks, routes, or waypoints) |
| FR-2 | Users can draw a route interactively on a map |
| FR-3 | Users can search and select a named trail from an integrated trail database (e.g., OpenStreetMap hiking relations) |
| FR-4 | The system accepts multi-day routes and performs per-day segment analysis where applicable |

### 5.2 Snow Analysis

| ID   | Requirement |
|------|-------------|
| FR-5 | For each point on the route, the system reports the most recent available FSC value and its acquisition date |
| FR-6 | The system reports the percentage of the route that is snow-covered, snow-free, cloud-obscured, or unavailable |
| FR-7 | The system classifies each snow-covered segment as **low-risk** or **high-risk** based on terrain slope (derived from a DEM) |
| FR-8 | Slope threshold for high-risk classification is configurable; default is ≥ 30° |
| FR-9 | Where satellite data is cloud-obscured, the system uses the most recent clear-sky observation within the previous N days (configurable, default 7 days) and clearly labels it as "last seen N days ago" |
| FR-10 | The system displays a map view of the route overlaid on the snow coverage raster |

### 5.3 Auxiliary Data

| ID   | Requirement |
|------|-------------|
| FR-11 | The system integrates short-range weather forecast snowfall data (next 3–5 days) to warn of expected new snowfall on the route |
| FR-12 | The system shows nearby webcam images for user visual validation |
| FR-13 | Users can submit a "conditions report" (text + optional photo) for a location, tagged with GPS coordinates and date |
| FR-14 | User-submitted reports are displayed on the map and associated with nearby route segments |

### 5.4 Output and Reporting

| ID   | Requirement |
|------|-------------|
| FR-15 | The system produces a summary card: % snow-covered, % on steep terrain, data age, overall safety indicator (green / amber / red) |
| FR-16 | The system produces a detailed per-segment breakdown downloadable as PDF or shareable as a URL |
| FR-17 | Users can view historical snow coverage for the same route on a date slider |

### 5.5 User Accounts

| ID   | Requirement |
|------|-------------|
| FR-18 | Users can create accounts to save routes and receive alerts |
| FR-19 | Users can set up alerts: "notify me when snow coverage on my saved route drops below X%" |
| FR-20 | Anonymous (no-account) usage is supported for basic route analysis |

---

## 6. Non-Functional Requirements

| ID    | Category       | Requirement |
|-------|----------------|-------------|
| NFR-1 | Performance    | Route analysis for a standard day-hike route (< 25 km) returns results within 5 seconds |
| NFR-2 | Performance    | Map tile rendering is fluid on mobile devices (60 fps pan/zoom) |
| NFR-3 | Availability   | Core snow-analysis service targets 99.5% monthly uptime |
| NFR-4 | Data freshness | FSC data is ingested and indexed within 2 hours of CLMS product publication |
| NFR-5 | Scalability    | The backend can process up to 1,000 simultaneous route analysis requests |
| NFR-6 | Mobile         | The web application is fully responsive; native mobile apps target iOS 16+ and Android 10+ |
| NFR-7 | Offline        | Mobile app caches the last-retrieved analysis for a saved route for offline review |
| NFR-8 | Accessibility  | Web UI complies with WCAG 2.1 AA |
| NFR-9 | Localisation   | UI supports English, German, French, Italian as initial languages |

---

## 7. Data Sources

### 7.1 Primary — Copernicus FSC (Fractional Snow Cover)

| Attribute        | Value |
|------------------|-------|
| Provider         | Copernicus Land Monitoring Service (CLMS) |
| Product          | HR-WSI FSC — FSCTOC (Top of Canopy), FSCOG (On-ground) |
| URL              | https://land.copernicus.eu/en/products/snow/fractional-snow-cover |
| Spatial res.     | 20 m |
| Temporal res.    | Per Sentinel-2 overpass (~1–5 days per pixel depending on latitude) |
| Encoding         | GeoTIFF uint8: 0–100 = FSC %, 205 = cloud, 210 = water, 255 = no data/snow-free (NDSI layer) |
| Latency          | Near-real-time; typically available within 24 h of acquisition |
| Access           | Free; HDA (Harmonised Data Access) API and direct HTTPS download |
| Coverage         | EEA38+UK initially; expanding globally via alternative sensors |

### 7.2 Secondary — Digital Elevation Model (DEM)

| Attribute        | Value |
|------------------|-------|
| Product          | Copernicus DEM GLO-30 (30 m global) |
| Use              | Derive terrain slope for risk classification |
| Access           | Freely available via AWS S3 / Copernicus SFTP |

### 7.3 Auxiliary Sources

| Source                        | Use                                      | Access |
|-------------------------------|------------------------------------------|--------|
| Open-Meteo / ECMWF IFS        | Short-range precipitation/snowfall forecast | Free REST API |
| OpenSnowMap / OpenStreetMap   | Trail geometry for named-route search    | Free / Overpass API |
| Webcam APIs (windy.com, etc.) | Nearby webcam images for visual confirmation | 3rd-party API |
| User-submitted reports        | Ground-truth crowd-sourced conditions   | Own backend |
| MODIS Terra/Aqua (500 m)      | Fallback / gap-filling for areas outside Sentinel-2 coverage | NASA LAADS / HDF |

---

## 8. System Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                          CLIENTS                                 │
│         Web App (React)            Mobile App (React Native)     │
└───────────────────────┬──────────────────────────────────────────┘
                        │  HTTPS / REST + WebSocket
┌───────────────────────▼──────────────────────────────────────────┐
│                      API Gateway / CDN                           │
│              (rate limiting, auth, caching, routing)             │
└─────┬─────────────────────────────────────────┬──────────────────┘
      │                                         │
┌─────▼──────────────┐               ┌──────────▼─────────────────┐
│   Route Analysis   │               │     Tile / Map Service     │
│      Service       │               │  (pre-rendered FSC tiles,  │
│  (Python/FastAPI)  │               │   vector trail overlay)    │
└─────┬──────────────┘               └────────────────────────────┘
      │
┌─────▼──────────────────────────────────────────────────────────┐
│                     Core Processing Layer                       │
│                                                                 │
│  ┌───────────────┐  ┌──────────────┐  ┌─────────────────────┐  │
│  │  FSC Indexer  │  │ Slope Engine │  │  Gap-Fill / Fusion  │  │
│  │ (rasterio,    │  │ (DEM + FSC   │  │  (temporal mosaic,  │  │
│  │  pyproj)      │  │  per pixel)  │  │   MODIS fallback)   │  │
│  └───────┬───────┘  └──────┬───────┘  └──────────┬──────────┘  │
│          └─────────────────┴───────────────────────┘            │
│                             │                                   │
│                    ┌────────▼────────┐                          │
│                    │  Spatial Index  │                          │
│                    │  (PostGIS /     │                          │
│                    │   GeoParquet)   │                          │
│                    └─────────────────┘                          │
└────────────────────────────────────────────────────────────────┘
      │                          │
┌─────▼──────────┐    ┌──────────▼──────────┐
│  Data Ingestion │    │  Auxiliary Sources  │
│  Pipeline       │    │  (weather, webcams, │
│  (CLMS HDA API) │    │   user reports)     │
└────────────────┘    └─────────────────────┘
```

### 8.1 Architecture Principles

- **Separation of concerns**: data ingestion, spatial processing, and API serving are independent, independently scalable services.
- **Pre-computation where possible**: slope risk per pixel is computed once per DEM tile and cached; FSC-slope intersection is computed at ingest time, not at query time.
- **Graceful degradation**: if the latest FSC tile is cloud-covered, the system uses temporal gap-filling transparently and always communicates data age to the user.
- **Stateless API**: the route analysis service is stateless; all persistent state lives in the spatial database.

---

## 9. Component Design

### 9.1 Data Ingestion Service

**Responsibility:** Monitor CLMS for new FSC product releases, download, validate, and ingest them into the spatial database.

**Key steps:**
1. Poll CLMS HDA API (or subscribe to Copernicus push notifications) for new FSCTOC tiles.
2. Download GeoTIFF, validate CRC and metadata.
3. Run pre-processing: reclassify pixel values, reproject to WGS84 (EPSG:4326), generate Cloud-Optimised GeoTIFF (COG).
4. For each pixel, compute `(tile_id, date, col, row, fsc_value, slope_deg, risk_class)` and upsert into the spatial database.
5. Update the temporal gap-fill mosaic (most recent clear-sky value per pixel).
6. Publish ingestion event to message queue; tile service invalidates relevant cache entries.

### 9.2 Route Analysis Service

**Responsibility:** Given a route geometry (list of lat/lon points), return the snow analysis.

**Algorithm:**
```
Input: route_coords [(lat, lon), ...]

1. For each point in route_coords:
   a. Look up the most recent clear-sky FSC value from the spatial database.
   b. Look up the pre-computed slope value from the DEM index.
   c. Classify:
        FSC 0-100 + slope < 30° → snow_low_risk
        FSC 0-100 + slope ≥ 30° → snow_high_risk
        FSC 255 (snow-free)     → clear
        FSC 205                 → cloud_obscured
        FSC 210                 → water

2. Aggregate:
   - % of route per classification
   - Longest continuous snow_high_risk segment (metres)
   - Data age: oldest/newest acquisition date among points
   - Cloud gap: % of route with cloud-obscured data

3. Compute overall safety indicator:
   - GREEN  : < 5% snow, or all snow is low-risk and < 20%
   - AMBER  : 5–30% snow, or any high-risk snow present
   - RED    : > 30% snow, or > 10% high-risk snow, or > 40% cloud gap
              (confidence too low to assess)

4. Return structured JSON response.
```

### 9.3 Slope Engine

**Responsibility:** Pre-compute and cache per-pixel slope from the Copernicus DEM GLO-30.

- Slope is computed using the standard 8-neighbour Horn algorithm applied to the 30 m DEM.
- Output is a GeoTIFF (uint8, 0–90°) stored as a COG, spatially indexed.
- DEM tiles are processed once; they do not change.

### 9.4 Tile / Map Service

**Responsibility:** Serve pre-rendered coloured FSC raster tiles (XYZ scheme) and vector trail tiles (MVT).

- FSC tiles are rendered at ingestion time at zoom levels 6–14.
- Colour scheme matches the per-pixel risk classification: green (clear), blue gradient (snow by FSC%), grey (cloud), dark blue (water).
- Vector trail tiles are sourced from OpenStreetMap and updated weekly.
- CDN caches tile responses; cache TTL = 12 h for FSC tiles.

### 9.5 Gap-Fill / Temporal Fusion Engine

**Responsibility:** Maintain a "best available" mosaic per pixel — the most recent clear-sky observation within the last N days (default 7).

- On each new FSC product ingestion, for every newly cloud-free pixel, update the mosaic record with the new value and timestamp.
- Cloud-covered pixels retain their previous mosaic value until a cloud-free observation arrives.
- Pixels with no clear observation within N days are marked `data_stale`.

---

## 10. Data Pipeline

```
CLMS HDA API
    │
    ▼  (polling / webhook, every 1–4 h)
[Downloader]
    │  GeoTIFF (raw)
    ▼
[Validator]  ─── invalid ──→ [Dead Letter Queue + Alert]
    │  valid
    ▼
[Reprojector]  (EPSG:UTM → EPSG:4326, COG conversion)
    │
    ▼
[FSC Ingestor]  (per-pixel upsert into spatial DB)
    │
    ├──→ [Slope Join]  (JOIN with DEM slope index → risk_class column)
    │
    └──→ [Mosaic Updater]  (update gap-fill mosaic table)
              │
              └──→ [Tile Renderer]  (invalidate + re-render FSC XYZ tiles)
                        │
                        └──→ [CDN Cache Invalidation]
```

**Technology choices:**
- **Orchestration:** Apache Airflow or Prefect (DAG-based, retryable)
- **Processing:** Python (rasterio, numpy, pyproj, rio-cogeo)
- **Spatial database:** PostgreSQL + PostGIS, with GeoParquet for analytical queries
- **Message queue:** Redis Streams or RabbitMQ
- **Object storage:** S3-compatible (raw GeoTIFFs, COGs, rendered tiles)

---

## 11. User Interface Design

### 11.1 Web App — Main Screens

**Screen 1: Route Input**
- Full-screen interactive map (Leaflet or MapLibre GL JS)
- Top bar: "Upload GPX" button and "Draw route" toggle
- When drawing: click-to-add waypoints, auto-snap to trails (OSM)
- Right panel: route summary (distance, elevation profile)
- "Analyse Snow" CTA button

**Screen 2: Snow Analysis Results**
- Map view: route overlaid on FSC colour raster; segments colour-coded by classification
- Side panel (or bottom sheet on mobile):
  - Summary card with traffic-light indicator (GREEN / AMBER / RED)
  - Stats: % snow-covered, % high-risk, data age
  - Timeline slider: view historical snow on same route
  - "Download Report" / "Share Link" buttons
- Popups: tap/click a route point → popup shows FSC%, slope, data date, nearest webcam thumbnail

**Screen 3: Conditions Details**
- Per-segment table: distance, elevation, FSC%, slope, risk
- Webcam gallery (nearest webcams within 5 km of route)
- Weather forecast widget: next 5 days, snowfall risk
- Community reports: pins on map, sortable list

### 11.2 Mobile App

- Mirrors the web app flow optimised for one-thumb navigation
- Bottom sheet pattern for analysis results
- Offline cache: last analysis for each saved route, viewable without connectivity
- Push notifications for snow-condition alerts on saved routes

### 11.3 Safety Language Guidelines

To ensure non-specialist users understand the output:

| Technical term        | User-facing language                              |
|-----------------------|---------------------------------------------------|
| FSC > 0%, slope < 30° | "Snow present — passable with care"               |
| FSC > 0%, slope ≥ 30° | "Snow on steep terrain — crampons/ice axe advised"|
| FSC = 255 (snow-free) | "No snow detected"                                |
| FSC = 205 (cloud)     | "Satellite data unavailable (cloud cover)"        |
| Data age > 5 days     | "Warning: data is N days old — conditions may have changed" |

---

## 12. API Design

### 12.1 Route Analysis Endpoint

```
POST /api/v1/analyse

Request body:
{
  "route": {
    "type": "LineString",
    "coordinates": [[lon, lat], ...]   // GeoJSON
  },
  "options": {
    "steep_threshold_deg": 30,         // optional, default 30
    "max_data_age_days":   7           // optional, default 7
  }
}

Response:
{
  "summary": {
    "safety_indicator": "AMBER",
    "snow_covered_pct": 42.1,
    "high_risk_snow_pct": 8.3,
    "cloud_obscured_pct": 6.2,
    "data_age_days": { "min": 1, "max": 4, "mean": 2.1 }
  },
  "segments": [
    {
      "index": 0,
      "lat": 46.612, "lon": 8.034,
      "fsc_pct": 87,
      "slope_deg": 34.2,
      "risk_class": "snow_high_risk",
      "acquisition_date": "2026-05-23"
    },
    ...
  ],
  "nearby_webcams": [...],
  "forecast": { ... }
}
```

### 12.2 Tile Endpoints

```
GET /tiles/fsc/{z}/{x}/{y}.png          # FSC colour raster tiles
GET /tiles/trails/{z}/{x}/{y}.mvt       # OpenStreetMap trail vector tiles
GET /tiles/slope/{z}/{x}/{y}.png        # Slope risk overlay (optional)
```

### 12.3 User Reports Endpoint

```
POST /api/v1/reports
GET  /api/v1/reports?bbox=lon_min,lat_min,lon_max,lat_max&days=7
```

---

## 13. Key Challenges and Mitigations

### 13.1 Cloud Cover Gaps

**Challenge:** Sentinel-2 is an optical sensor. In mountainous areas, cloud cover can obscure a location for 7–14 consecutive days, especially in maritime climates. During such periods the FSC data is unavailable.

**Mitigations:**
- **Temporal gap-filling:** Use the most recent cloud-free observation (up to N days old) and prominently display its age.
- **MODIS fallback:** MODIS Terra/Aqua provides daily coverage at 500 m resolution. Use as a fallback for cloud-covered Sentinel-2 pixels where recency matters more than resolution.
- **Forecast integration:** When satellite data is stale, integrate snowfall forecast to indicate whether conditions are likely to have changed.
- **User communication:** Always display the data age; use "confidence indicator" language, not false precision.

### 13.2 Sentinel-2 Revisit Time

**Challenge:** A single Sentinel-2 tile has a revisit of 5 days at the equator, improving to 1–2 days at mid-latitudes (both S2A and S2B), but still leaves potential gaps for dynamic conditions.

**Mitigation:** Combine FSC products from overlapping adjacent tiles; use Sentinel-2 cross-orbit overlap in high-latitude regions to reduce effective revisit time.

### 13.3 Steep Terrain Snow Detection Accuracy

**Challenge:** The FSC algorithm is less accurate in areas of terrain shadow (hillshade) and on very steep faces, where the optical signal is affected by illumination geometry.

**Mitigation:** The CLMS FSC product includes a `QAFLAGS` layer with a dedicated hillshade flag (bit 0) and low-illumination flag (bit 4). Use these flags to downgrade confidence for affected pixels and show warnings.

### 13.4 Snow vs. Cloud Misclassification

**Challenge:** In early-season or under thin cloud, the FSC algorithm may misclassify cloud as snow or vice versa.

**Mitigation:** The FSC product's `CLD` (MAJA cloud mask) layer separates cloud from snow. The pipeline should use `CLD` to mask uncertain pixels rather than relying on FSC value alone.

### 13.5 DEM–FSC Alignment

**Challenge:** The DEM (GLO-30, 30 m) and FSC (20 m) have different spatial resolutions and projections. Slope assignment per FSC pixel requires careful spatial join.

**Mitigation:** Reproject the DEM to match each FSC tile's UTM CRS and resample to 20 m using bilinear interpolation before computing slope. Pre-compute and store slope as a persistent raster layer.

### 13.6 Global Data Volume

**Challenge:** At global scale, the FSC product catalogue is large (thousands of 100×100 km tiles, daily). Full global ingestion may not be feasible at launch.

**Mitigation:** Launch with **progressive geographic rollout** — Alps first, then Pyrenees, Scandinavia, Himalayas, Rockies — prioritised by user demand signal. Add a "request coverage for this region" feature.

### 13.7 Latency of Analysis Response

**Challenge:** Running rasterio point sampling across thousands of GPX track points against large GeoTIFFs at query time is too slow.

**Mitigation:** Pre-index FSC and slope values into PostGIS at ingestion time. Route analysis at query time becomes a spatial point-in-polygon database lookup (sub-second for typical routes).

---

## 14. Security and Privacy

| Area | Requirement |
|------|-------------|
| Authentication | OAuth 2.0 / OpenID Connect for user accounts; JWT bearer tokens for API |
| Anonymous use | Basic route analysis available without account; no GPS data stored for anonymous users |
| User data | GPX uploads processed in memory and not persisted without explicit user save action |
| User reports | GPS coordinates rounded to 50 m before storage to reduce location precision |
| API rate limiting | Anonymous: 10 req/min; authenticated: 100 req/min |
| Transport security | TLS 1.3 minimum on all endpoints |
| Dependency scanning | Automated CVE scanning in CI/CD pipeline (e.g., Dependabot) |
| GDPR | Data Processing Agreement available; users in EEA can export and delete their data |

---

## 15. Testing Strategy

### 15.1 Unit Tests
- FSC pixel classification logic
- Slope risk classifier (boundary conditions at 30°)
- Temporal gap-fill mosaic update logic
- GPX parser edge cases (empty files, waypoints only, malformed coordinates)

### 15.2 Integration Tests
- End-to-end ingestion pipeline with synthetic GeoTIFF fixtures
- Route analysis API with known routes and pre-seeded database state

### 15.3 Accuracy Validation
- Select 20 reference routes with known historical conditions (from verified trip reports)
- Compare SnowRoute output against ground truth for those dates
- Target: classification accuracy ≥ 85% on labelled reference set

### 15.4 Performance Tests
- Route analysis endpoint: p95 latency < 3 s under 500 concurrent users
- Tile server: p99 latency < 200 ms per tile under load

### 15.5 UI / UX Tests
- Usability testing with 5 users from each persona group before public beta
- Accessibility audit (WCAG 2.1 AA compliance check)

---

## 16. Deployment and Infrastructure

### 16.1 Technology Stack Summary

| Layer               | Technology |
|---------------------|------------|
| Web frontend        | React + MapLibre GL JS |
| Mobile app          | React Native |
| API service         | Python / FastAPI |
| Spatial database    | PostgreSQL 16 + PostGIS 3 |
| Object storage      | AWS S3 (or S3-compatible) |
| Pipeline orchestration | Prefect |
| Tile server         | TiTiler (Python) or Martin (Rust) |
| CDN                 | CloudFront / Cloudflare |
| Container runtime   | Docker + Kubernetes |
| CI/CD               | GitHub Actions |
| Monitoring          | Prometheus + Grafana |
| Error tracking      | Sentry |

### 16.2 Environments

| Environment | Purpose |
|-------------|---------|
| Development | Local Docker Compose; developer laptops |
| Staging | Full cloud deployment; uses real CLMS data; accessible to testers |
| Production | Multi-AZ; auto-scaling; monitored |

### 16.3 MVP Scope (Phase 1)

For the Minimum Viable Product, the following subset is sufficient:

- [x] Alpine region FSC data ingestion (CLMS, single-region)
- [x] Route analysis API (GPX upload only)
- [x] Web app with map view and summary card
- [x] Slope risk classification
- [x] Temporal gap-fill (7-day window)
- [ ] Mobile app *(Phase 2)*
- [ ] Draw-on-map route input *(Phase 2)*
- [ ] Weather forecast integration *(Phase 2)*
- [ ] Community reports *(Phase 3)*
- [ ] Global coverage rollout *(ongoing)*

---

## 17. Open Questions

| ID  | Question | Owner | Target date |
|-----|----------|-------|-------------|
| OQ-1 | What is the licensing model — freemium SaaS, open source, or institutional? This affects architecture decisions around multi-tenancy, API key management, and billing. | Product | TBD |
| OQ-2 | Should the tool integrate Sentinel-1 SAR wet snow products (also from CLMS) to improve detection under cloud cover? SAR is cloud-independent but detects only wet (melting) snow. | Technical | TBD |
| OQ-3 | What is the target latency SLA for the data pipeline? How quickly after a Sentinel-2 overpass must the updated analysis be visible to users? | Product | TBD |
| OQ-4 | Is crowd-sourced user reporting in scope for the MVP, or is it a later phase? User-generated content introduces moderation requirements. | Product | TBD |
| OQ-5 | Should the tool produce an avalanche risk advisory, or strictly limit itself to snow presence / route passability? Avalanche advisory requires specialist meteorological data and legal liability considerations. | Legal / Product | TBD |
| OQ-6 | What trail database (OpenStreetMap, Komoot, AllTrails partnership) will be used for named-route search? Licensing differs significantly. | Legal | TBD |

---

*End of document.*
