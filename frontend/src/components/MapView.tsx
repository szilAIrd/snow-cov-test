import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { AnalysisResponse, RiskClass } from "../types";

const NON_SNOW_COLOR: Partial<Record<RiskClass, string>> = {
  clear: "#22c55e",
  cloud_obscured: "#94a3b8",
  water: "#1e40af",
};

/**
 * Blue (#3b82f6) → white (#ffffff) gradient keyed on FSC 0–100.
 * Low FSC = sparse patchy snow = more blue.
 * High FSC = deep snow cover = more white.
 */
export function fscToColor(fscPct: number | null): string {
  // Matches the backend _fsc_to_rgba_overlay colour scheme:
  // vivid cornflower-blue (#2878FF) at 0 % → ice white at 100 %
  const pct = Math.max(0, Math.min(100, fscPct ?? 50)) / 100;
  const r = Math.round( 40 + 215 * pct);
  const g = Math.round(120 + 135 * pct);
  const b = 255;
  return `rgb(${r},${g},${b})`;
}

function segmentColor(riskClass: RiskClass, fscPct: number | null): string {
  return NON_SNOW_COLOR[riskClass] ?? fscToColor(fscPct);
}

const RISK_LABEL: Record<RiskClass, string> = {
  clear: "No snow",
  snow_low_risk: "Snow – low risk",
  snow_high_risk: "Snow – HIGH RISK (steep)",
  cloud_obscured: "Cloud / no data",
  water: "Water",
};

/**
 * Backend FSC tile URL — serves Copernicus-style FSCOG coverage tiles
 * rendered from the synthetic elevation model (replace with PostGIS/TiTiler
 * query against real CLMS HR-WSI data when the data pipeline is live).
 * Standard XYZ order: {z}/{x}/{y}.
 */
function fscTileUrl(date: string): string {
  return `/api/v1/tiles/fsc/{z}/{x}/{y}.png?date=${date}`;
}

interface Props {
  analysis: AnalysisResponse | null;
  /** Show the FSC snow coverage raster layer */
  showSnowLayer: boolean;
  /** ISO date (YYYY-MM-DD) for the snow coverage layer */
  snowLayerDate: string;
  /** Raster opacity 0–1 */
  snowLayerOpacity: number;
  /** Show or hide the OpenStreetMap base layer (default true) */
  showOsmLayer: boolean;
}

export function MapView({
  analysis,
  showSnowLayer,
  snowLayerDate,
  snowLayerOpacity,
  showOsmLayer,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  // Keep a ref so the opacity effect never needs to rebuild the source
  const opacityRef = useRef(snowLayerOpacity);

  // Initialise map once
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    mapRef.current = new maplibregl.Map({
      container: containerRef.current,
      // Free OpenStreetMap-based style — no API key required
      style: {
        version: 8,
        sources: {
          osm: {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "© OpenStreetMap contributors",
          },
        },
        layers: [{ id: "osm", type: "raster", source: "osm" }],
      },
      center: [10.0, 46.5],
      zoom: 7,
    });

    mapRef.current.addControl(new maplibregl.NavigationControl(), "top-right");

    return () => {
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, []);

  // ── OSM base-map visibility toggle ─────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () =>
      map.setLayoutProperty("osm", "visibility", showOsmLayer ? "visible" : "none");
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [showOsmLayer]);

  // ── FSC snow coverage raster layer (backend tile endpoint) ───────────────
  // Rebuilds source + layer when visibility or date changes.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const apply = () => {
      if (map.getLayer("snow-cover")) map.removeLayer("snow-cover");
      if (map.getSource("snow-src")) map.removeSource("snow-src");

      if (!showSnowLayer) return;

      map.addSource("snow-src", {
        type: "raster",
        tiles: [fscTileUrl(snowLayerDate)],
        tileSize: 256,
        maxzoom: 12,
        attribution: "© Copernicus Land Monitoring Service · HR-WSI FSC (synthetic)",
      });

      // Insert below route analysis layers so they always render on top
      const beforeId = map.getLayer("route-line") ? "route-line" : undefined;
      map.addLayer(
        {
          id: "snow-cover",
          type: "raster",
          source: "snow-src",
          paint: { "raster-opacity": opacityRef.current },
        },
        beforeId
      );
    };

    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [showSnowLayer, snowLayerDate]); // eslint-disable-line react-hooks/exhaustive-deps

  // Update opacity in-place (no tile re-fetch needed)
  useEffect(() => {
    opacityRef.current = snowLayerOpacity;
    const map = mapRef.current;
    if (!map?.getLayer("snow-cover")) return;
    map.setPaintProperty("snow-cover", "raster-opacity", snowLayerOpacity);
  }, [snowLayerOpacity]);

  // ── Route analysis layer ─────────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const addLayers = () => {
      // Remove previous layers / sources
      ["route-line", "route-points"].forEach((id) => {
        if (map.getLayer(id)) map.removeLayer(id);
      });
      ["route-source", "points-source"].forEach((id) => {
        if (map.getSource(id)) map.removeSource(id);
      });

      if (!analysis) return;

      const { segments } = analysis;

      // Route line (full track)
      const lineCoords = segments.map((s) => [s.lon, s.lat]);
      map.addSource("route-source", {
        type: "geojson",
        data: {
          type: "Feature",
          properties: {},
          geometry: { type: "LineString", coordinates: lineCoords },
        },
      });
      map.addLayer({
        id: "route-line",
        type: "line",
        source: "route-source",
        paint: { "line-color": "#475569", "line-width": 2, "line-opacity": 0.5 },
      });

      // Per-segment coloured points
      const features: GeoJSON.Feature[] = segments.map((s) => ({
        type: "Feature",
        properties: {
          risk_class: s.risk_class,
          fsc_pct: s.fsc_pct,
          slope_deg: s.slope_deg,
          acquisition_date: s.acquisition_date,
          // Fill: FSC blue→white gradient for snow; fixed colour otherwise
          color: segmentColor(s.risk_class, s.fsc_pct),
          // Stroke: red border flags steep high-risk snow
          stroke: s.risk_class === "snow_high_risk" ? "#dc2626" : "#fff",
          stroke_width: s.risk_class === "snow_high_risk" ? 2 : 1,
        },
        geometry: { type: "Point", coordinates: [s.lon, s.lat] },
      }));

      map.addSource("points-source", {
        type: "geojson",
        data: { type: "FeatureCollection", features },
      });

      map.addLayer({
        id: "route-points",
        type: "circle",
        source: "points-source",
        paint: {
          "circle-radius": 5,
          "circle-color": ["get", "color"],
          "circle-stroke-color": ["get", "stroke"],
          "circle-stroke-width": ["get", "stroke_width"],
        },
      });

      // Popup on click
      map.on("click", "route-points", (e) => {
        const feat = e.features?.[0];
        if (!feat || feat.geometry.type !== "Point") return;
        const p = feat.properties as {
          risk_class: RiskClass;
          fsc_pct: number | null;
          slope_deg: number;
          acquisition_date: string;
        };
        const snowColor =
          p.fsc_pct != null
            ? `<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${fscToColor(p.fsc_pct)};border:1px solid #94a3b8;vertical-align:middle;margin-right:4px"></span>`
            : "";
        const html = `
          <strong>${RISK_LABEL[p.risk_class]}</strong><br/>
          ${snowColor}FSC: ${p.fsc_pct != null ? p.fsc_pct + "% (" + (p.fsc_pct < 40 ? "low" : p.fsc_pct < 70 ? "medium" : "high") + ")" : "n/a"}<br/>
          Slope: ${p.slope_deg}°<br/>
          Data date: ${p.acquisition_date}
        `;
        new maplibregl.Popup({ closeButton: false })
          .setLngLat(feat.geometry.coordinates as [number, number])
          .setHTML(html)
          .addTo(map);
      });

      map.on("mouseenter", "route-points", () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "route-points", () => {
        map.getCanvas().style.cursor = "";
      });

      // Fit map to route
      if (lineCoords.length > 1) {
        const lngs = lineCoords.map((c) => c[0]);
        const lats = lineCoords.map((c) => c[1]);
        map.fitBounds(
          [
            [Math.min(...lngs), Math.min(...lats)],
            [Math.max(...lngs), Math.max(...lats)],
          ],
          { padding: 60, maxZoom: 14 }
        );
      }
    };

    if (map.isStyleLoaded()) {
      addLayers();
    } else {
      map.once("load", addLayers);
    }
  }, [analysis]);

  return <div ref={containerRef} className="map-container" />;
}
