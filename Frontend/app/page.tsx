"use client";

import { useEffect, useMemo, useState } from "react";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

const BISHKEK = {
  lat: 42.8746,
  lon: 74.5698,
};

type Source = {
  id: number;
  external_id: string;
  name: string;
  city: string | null;
  country: string | null;
  provider: string;
  latitude: number;
  longitude: number;
  distance_km: number | null;
  last_successful_update: string | null;
};

type Measurement = {
  timestamp: string;
  pm25: number | null;
  pm10: number | null;
  no2: number | null;
  co: number | null;
  o3: number | null;
  temperature: number | null;
  humidity: number | null;
  wind_speed: number | null;
};

type NearbyResponse = {
  source: Source;
  latest_measurement: Measurement | null;
  forecast: {
    generated: boolean;
    points_created: number;
  };
  meta: {
    source_was_created: boolean;
  };
};

type ForecastPoint = {
  target_time: string;
  horizon_hours: number;
  predicted_aqi: number | null;
  predicted_pm25: number | null;
  predicted_pm10: number | null;
  predicted_no2: number | null;
  predicted_co: number | null;
  predicted_o3: number | null;
  confidence_score: number | null;
  ci_lower: number | null;
  ci_upper: number | null;
};

type ForecastResponse = {
  station: {
    id: number;
    name: string;
    city: string | null;
    country: string | null;
    provider: string;
  };
  generated_at: string | null;
  model: {
    name: string;
    version: string | null;
  } | null;
  predictions: ForecastPoint[];
};

function pm25ToAQI(pm25: number | null) {
  if (pm25 === null) return null;

  const breakpoints = [
    [0.0, 9.0, 0, 50],
    [9.1, 35.4, 51, 100],
    [35.5, 55.4, 101, 150],
    [55.5, 125.4, 151, 200],
    [125.5, 225.4, 201, 300],
    [225.5, 325.4, 301, 500],
  ];

  for (const [cLow, cHigh, iLow, iHigh] of breakpoints) {
    if (pm25 >= cLow && pm25 <= cHigh) {
      return Math.round(
        ((iHigh - iLow) / (cHigh - cLow)) * (pm25 - cLow) + iLow
      );
    }
  }

  return 500;
}

function getAQIState(aqi: number | null) {
  if (aqi === null) {
    return {
      label: "No data",
      className: "neutral",
      message: "Waiting for environmental data.",
    };
  }

  if (aqi <= 50) {
    return {
      label: "Good",
      className: "good",
      message: "Air conditions are currently favorable.",
    };
  }

  if (aqi <= 100) {
    return {
      label: "Moderate",
      className: "moderate",
      message: "Air quality is acceptable for most people.",
    };
  }

  if (aqi <= 150) {
    return {
      label: "Elevated",
      className: "elevated",
      message: "Pollution levels are above cleaner conditions.",
    };
  }

  return {
    label: "High",
    className: "high",
    message: "Air pollution is currently elevated.",
  };
}

function formatValue(
  value: number | null | undefined,
  digits = 1
) {
  if (value === null || value === undefined) {
    return "—";
  }

  return value.toFixed(digits);
}

function formatUpdatedAt(value: string | null | undefined) {
  if (!value) return "Not available";

  try {
    return new Intl.DateTimeFormat("en", {
      hour: "2-digit",
      minute: "2-digit",
      day: "numeric",
      month: "short",
    }).format(new Date(value));
  } catch {
    return "Recently";
  }
}

export default function Home() {
  const [nearby, setNearby] = useState<NearbyResponse | null>(null);
  const [forecast, setForecast] = useState<ForecastResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [locationLabel, setLocationLabel] = useState("Locating you...");
  const [usingDemo, setUsingDemo] = useState(false);

  async function loadData(
    latitude: number,
    longitude: number,
    demo = false
  ) {
    setLoading(true);
    setError(null);
    setUsingDemo(demo);

    try {
      const nearbyResponse = await fetch(
        `${API_URL}/api/v1/gis/nearby?lat=${latitude}&lon=${longitude}`,
        {
          cache: "no-store",
        }
      );

      if (!nearbyResponse.ok) {
        throw new Error(
          `Nearby API failed with ${nearbyResponse.status}`
        );
      }

      const nearbyData: NearbyResponse = await nearbyResponse.json();
      setNearby(nearbyData);

      const stationId = nearbyData.source.id;

      const forecastResponse = await fetch(
        `${API_URL}/api/v1/analytics/forecast/${stationId}`,
        {
          cache: "no-store",
        }
      );

      if (forecastResponse.ok) {
        const forecastData: ForecastResponse =
          await forecastResponse.json();
        setForecast(forecastData);
      }

      const city = nearbyData.source.city || "Detected location";
      const country = nearbyData.source.country
        ? `, ${nearbyData.source.country}`
        : "";

      setLocationLabel(`${city}${country}`);
    } catch (err) {
      console.error(err);
      setError(
        "AIRPredict could not reach the environmental data service."
      );
    } finally {
      setLoading(false);
    }
  }

  function useMyLocation() {
    setLoading(true);
    setError(null);
    setLocationLabel("Locating you...");

    if (!navigator.geolocation) {
      setError("Geolocation is not supported.");
      setLoading(false);
      return;
    }

    navigator.geolocation.getCurrentPosition(
      (position) => {
        loadData(
          position.coords.latitude,
          position.coords.longitude,
          false
        );
      },
      () => {
        setLocationLabel("Bishkek demo");
        loadData(BISHKEK.lat, BISHKEK.lon, true);
      },
      {
        enableHighAccuracy: true,
        timeout: 10000,
        maximumAge: 60000,
      }
    );
  }

  function loadBishkek() {
    setLocationLabel("Bishkek demo");
    loadData(BISHKEK.lat, BISHKEK.lon, true);
  }

  useEffect(() => {
    useMyLocation();
  }, []);

  const measurement = nearby?.latest_measurement || null;
  const currentAQI = pm25ToAQI(measurement?.pm25 ?? null);
  const aqiState = getAQIState(currentAQI);
  const forecastPoints = forecast?.predictions || [];

  const chartPoints = useMemo(() => {
    if (!forecastPoints.length) return "";

    const values = forecastPoints
      .map((item) => item.predicted_aqi)
      .filter((value): value is number => value !== null);

    if (!values.length) return "";

    const min = Math.min(...values);
    const max = Math.max(...values);

    const width = 600;
    const height = 180;

    return forecastPoints
      .map((item, index) => {
        const value = item.predicted_aqi ?? min;
        const x =
          (index / Math.max(forecastPoints.length - 1, 1)) * width;
        const normalized =
          max === min ? 0.5 : (value - min) / (max - min);
        const y = height - normalized * (height - 40) - 20;

        return `${x},${y}`;
      })
      .join(" ");
  }, [forecastPoints]);

  const mapEmbedUrl = useMemo(() => {
    const lat = nearby?.source.latitude ?? BISHKEK.lat;
    const lon = nearby?.source.longitude ?? BISHKEK.lon;

    const left = lon - 0.06;
    const right = lon + 0.06;
    const top = lat + 0.03;
    const bottom = lat - 0.03;

    return `https://www.openstreetmap.org/export/embed.html?bbox=${left}%2C${bottom}%2C${right}%2C${top}&layer=mapnik&marker=${lat}%2C${lon}`;
  }, [nearby]);

  return (
    <main className="site-shell">
      <div className="bg-orb orb-one" />
      <div className="bg-orb orb-two" />
      <div className="bg-grid" />

      <nav className="navbar">
        <div className="logo-area">
          <div className="logo-symbol">
            <span />
            A
          </div>

          <div>
            <strong>AIRPredict</strong>
            <small>Air quality intelligence</small>
          </div>
        </div>

        <div className="nav-right">
          <div className="live-indicator">
            <span />
            Live system
          </div>

          <div className="location-chip">
            <LocationIcon />
            {locationLabel}
          </div>
        </div>
      </nav>

      <section className="hero">
        <div className="hero-copy">
          <div className="hero-tag">
            <span />
            LOCATION-AWARE ATMOSPHERIC INSIGHT
          </div>

          <h1>
            Clean data for
            <br />
            <span>the air around you.</span>
          </h1>

          <p className="hero-lead">
            AIRPredict translates local environmental signals
            into simple, understandable air-quality insights and
            short-term forecasts.
          </p>

          <div className="hero-actions">
            <button className="button-primary" onClick={useMyLocation}>
              <LocationIcon />
              Use my location
            </button>

            <button className="button-secondary" onClick={loadBishkek}>
              Explore live demo
              <ArrowIcon />
            </button>
          </div>

          <div className="hero-proof">
            <div>
              <strong>72h</strong>
              <span>forecast horizon</span>
            </div>

            <div>
              <strong>10 min</strong>
              <span>backend refresh loop</span>
            </div>

            <div>
              <strong>Dynamic</strong>
              <span>source selection</span>
            </div>
          </div>
        </div>

        <div className="hero-visual">
          <div className={`air-card ${aqiState.className}`}>
            <div className="air-card-top">
              <div>
                <span className="micro-label">CURRENT AIR QUALITY</span>
                <p>
                  {nearby?.source.city ||
                    (usingDemo ? "Bishkek" : "Your location")}
                </p>
              </div>

              <div className="live-badge">
                <span />
                LIVE
              </div>
            </div>

            <div className="aqi-main">
              <div className="aqi-value">
                {loading ? <div className="skeleton-value" /> : currentAQI ?? "—"}
              </div>

              <div className="aqi-info">
                <strong>{aqiState.label}</strong>
                <span>US AQI</span>
              </div>
            </div>

            <p className="aqi-message">
              {loading
                ? "Connecting to environmental sources..."
                : aqiState.message}
            </p>

            <div className="mini-metrics">
              <div>
                <span>PM2.5</span>
                <strong>{formatValue(measurement?.pm25)}</strong>
                <small>µg/m³</small>
              </div>

              <div>
                <span>Temperature</span>
                <strong>{formatValue(measurement?.temperature)}</strong>
                <small>°C</small>
              </div>

              <div>
                <span>Wind</span>
                <strong>{formatValue(measurement?.wind_speed)}</strong>
                <small>m/s</small>
              </div>
            </div>

            <div className="air-card-footer">
              <span>Source: {nearby?.source.provider || "Connecting"}</span>
              <span>
                Updated {formatUpdatedAt(nearby?.source.last_successful_update)}
              </span>
            </div>
          </div>

          <div className="floating-card floating-card-one">
            <div className="floating-icon">
              <ForecastIcon />
            </div>

            <div>
              <span>Forecast engine</span>
              <strong>{forecastPoints.length || 0} points ready</strong>
            </div>
          </div>

          <div className="floating-card floating-card-two">
            <div className="floating-dot" />

            <div>
              <span>Source provider</span>
              <strong>{nearby?.source.provider || "Connecting"}</strong>
            </div>
          </div>
        </div>
      </section>

      {error && (
        <div className="notice-bar">
          <div>
            <strong>Connection issue</strong>
            <span>{error}</span>
          </div>

          <button onClick={loadBishkek}>Retry demo</button>
        </div>
      )}

      <section className="stats-strip">
        <StatPill
          label="Current AQI"
          value={currentAQI !== null ? String(currentAQI) : "—"}
        />
        <StatPill
          label="PM2.5"
          value={`${formatValue(measurement?.pm25)} µg/m³`}
        />
        <StatPill
          label="Humidity"
          value={`${formatValue(measurement?.humidity, 0)}%`}
        />
        <StatPill
          label="Forecast points"
          value={String(forecastPoints.length || 0)}
        />
      </section>

      <section className="dashboard-section">
        <div className="section-header">
          <div>
            <span className="section-kicker">LIVE ENVIRONMENTAL SNAPSHOT</span>
            <h2>Your air, decoded.</h2>
          </div>

          <p>
            Current pollution and weather indicators from the
            best available source near the selected location.
          </p>
        </div>

        <div className="metric-grid">
          <Metric
            label="PM2.5"
            value={formatValue(measurement?.pm25)}
            unit="µg/m³"
            description="Fine particles"
          />
          <Metric
            label="PM10"
            value={formatValue(measurement?.pm10)}
            unit="µg/m³"
            description="Coarse particles"
          />
          <Metric
            label="NO₂"
            value={formatValue(measurement?.no2)}
            unit="µg/m³"
            description="Nitrogen dioxide"
          />
          <Metric
            label="O₃"
            value={formatValue(measurement?.o3)}
            unit="µg/m³"
            description="Ground-level ozone"
          />
          <Metric
            label="Temperature"
            value={formatValue(measurement?.temperature)}
            unit="°C"
            description="Local weather"
          />
          <Metric
            label="Humidity"
            value={formatValue(measurement?.humidity, 0)}
            unit="%"
            description="Relative humidity"
          />
        </div>
      </section>

      <section className="forecast-section">
        <div className="section-header">
          <div>
            <span className="section-kicker">PREDICTIVE LAYER</span>
            <h2>What happens next?</h2>
          </div>

          <p>
            A 72-hour baseline forecast generated from recent
            pollution conditions and local environmental factors.
          </p>
        </div>

        <div className="forecast-panel">
          <div className="chart-column">
            <div className="chart-heading">
              <div>
                <span>AQI FORECAST</span>
                <strong>Next 72 hours</strong>
              </div>

              <div className="model-chip">
                {forecast?.model?.name || "environmental_baseline"}
              </div>
            </div>

            {forecastPoints.length ? (
              <>
                <div className="chart-wrapper">
                  <div className="chart-grid-line top" />
                  <div className="chart-grid-line middle" />
                  <div className="chart-grid-line bottom" />

                  <svg
                    viewBox="0 0 600 180"
                    preserveAspectRatio="none"
                    className="forecast-chart"
                  >
                    <defs>
                      <linearGradient
                        id="chartFillBlue"
                        x1="0"
                        x2="0"
                        y1="0"
                        y2="1"
                      >
                        <stop offset="0%" stopColor="#4ecbff" stopOpacity="0.30" />
                        <stop offset="100%" stopColor="#4ecbff" stopOpacity="0" />
                      </linearGradient>
                    </defs>

                    <polyline
                      points={`0,180 ${chartPoints} 600,180`}
                      fill="url(#chartFillBlue)"
                      stroke="none"
                    />

                    <polyline
                      points={chartPoints}
                      fill="none"
                      stroke="#55c9ff"
                      strokeWidth="4"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </div>

                <div className="chart-labels">
                  {forecastPoints.map((point) => (
                    <span key={point.horizon_hours}>+{point.horizon_hours}h</span>
                  ))}
                </div>
              </>
            ) : (
              <div className="forecast-loading">
                Forecast is being prepared...
              </div>
            )}
          </div>

          <div className="forecast-list">
            {forecastPoints.map((point) => (
              <div className="forecast-row" key={point.horizon_hours}>
                <div>
                  <span>+{point.horizon_hours} hours</span>
                  <small>
                    {point.confidence_score !== null
                      ? `${Math.round(point.confidence_score * 100)}% confidence`
                      : "Baseline estimate"}
                  </small>
                </div>

                <strong>
                  {point.predicted_aqi !== null
                    ? Math.round(point.predicted_aqi)
                    : "—"}
                  <small>AQI</small>
                </strong>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="map-section">
        <div className="section-header">
          <div>
            <span className="section-kicker">LOCALITY MAP</span>
            <h2>Where the data comes from.</h2>
          </div>

          <p>
            AIRPredict uses location-aware source matching and
            then visualizes the current source region on the map.
          </p>
        </div>

        <div className="map-panel">
          <div className="map-frame-wrap">
            <iframe
              title="AIRPredict source map"
              src={mapEmbedUrl}
              className="map-frame"
              loading="lazy"
            />
          </div>

          <div className="map-details">
            <div className="map-card">
              <span>Source name</span>
              <strong>{nearby?.source.name || "Environmental source"}</strong>
            </div>

            <div className="map-card">
              <span>Provider</span>
              <strong>{nearby?.source.provider || "—"}</strong>
            </div>

            <div className="map-card">
              <span>Coordinates</span>
              <strong>
                {nearby
                  ? `${nearby.source.latitude.toFixed(4)}, ${nearby.source.longitude.toFixed(4)}`
                  : `${BISHKEK.lat}, ${BISHKEK.lon}`}
              </strong>
            </div>

            <div className="map-card">
              <span>Distance</span>
              <strong>
                {nearby?.source.distance_km !== null &&
                nearby?.source.distance_km !== undefined
                  ? `${nearby.source.distance_km.toFixed(2)} km`
                  : "—"}
              </strong>
            </div>
          </div>
        </div>
      </section>

      <section className="process-section">
        <div className="section-header process-header">
          <div>
            <span className="section-kicker">HOW AIRPREDICT WORKS</span>
            <h2>From location to insight.</h2>
          </div>
        </div>

        <div className="process-grid">
          <ProcessCard
            number="01"
            title="Detect"
            text="AIRPredict uses the user's location to identify the most relevant environmental data source."
          />

          <ProcessCard
            number="02"
            title="Understand"
            text="Pollution and weather signals are normalized, stored and translated into a clear environmental snapshot."
          />

          <ProcessCard
            number="03"
            title="Forecast"
            text="AIRPredict generates a 72-hour baseline forecast so users can see how conditions may change."
          />
        </div>
      </section>

      <section className="impact-section">
        <div>
          <span className="section-kicker">WHY IT MATTERS</span>
          <h2>
            Air pollution is invisible.
            <br />
            Its impact isn&apos;t.
          </h2>
        </div>

        <div className="impact-copy">
          <p>
            Environmental data often exists, but it is fragmented,
            technical and difficult for everyday users to interpret.
          </p>

          <p>
            AIRPredict turns that data into a simple, local and
            actionable experience.
          </p>
        </div>
      </section>

      <section className="source-section">
        <div>
          <span className="section-kicker">CURRENT DATA SOURCE</span>
          <h3>{nearby?.source.name || "Environmental source"}</h3>
          <p>
            {nearby?.source.city || "Location"}
            {nearby?.source.country ? `, ${nearby.source.country}` : ""}
          </p>
        </div>

        <div className="source-stats">
          <div>
            <span>Provider</span>
            <strong>{nearby?.source.provider || "—"}</strong>
          </div>

          <div>
            <span>Distance</span>
            <strong>
              {nearby?.source.distance_km !== null &&
              nearby?.source.distance_km !== undefined
                ? `${nearby.source.distance_km.toFixed(2)} km`
                : "—"}
            </strong>
          </div>

          <div>
            <span>Forecast</span>
            <strong>{forecastPoints.length ? "Ready" : "Pending"}</strong>
          </div>
        </div>
      </section>

      <footer>
        <div className="logo-area footer-logo">
          <div className="logo-symbol">
            <span />
            A
          </div>

          <div>
            <strong>AIRPredict</strong>
            <small>Atmospheric intelligence</small>
          </div>
        </div>

        <p>
          Built to make local air-quality information clearer,
          faster and more usable.
        </p>
      </footer>
    </main>
  );
}

function Metric({
  label,
  value,
  unit,
  description,
}: {
  label: string;
  value: string;
  unit: string;
  description: string;
}) {
  return (
    <article className="metric-card">
      <div className="metric-card-top">
        <span>{label}</span>
        <div className="metric-indicator" />
      </div>

      <div className="metric-value">
        <strong>{value}</strong>
        <small>{unit}</small>
      </div>

      <p>{description}</p>
    </article>
  );
}

function ProcessCard({
  number,
  title,
  text,
}: {
  number: string;
  title: string;
  text: string;
}) {
  return (
    <article className="process-card">
      <span className="process-number">{number}</span>
      <div className="process-line" />
      <h3>{title}</h3>
      <p>{text}</p>
    </article>
  );
}

function StatPill({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="stat-pill">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function LocationIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="17"
      height="17"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
    >
      <path d="M12 21s6-5.2 6-11a6 6 0 1 0-12 0c0 5.8 6 11 6 11Z" />
      <circle cx="12" cy="10" r="2.2" />
    </svg>
  );
}

function ArrowIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="17"
      height="17"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
    >
      <path d="M5 12h14" />
      <path d="m14 7 5 5-5 5" />
    </svg>
  );
}

function ForecastIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="19"
      height="19"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
    >
      <path d="M4 18 9 13l3 3 7-8" />
      <path d="M15 8h4v4" />
    </svg>
  );
}