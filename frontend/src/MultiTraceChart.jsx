import React, { useMemo } from "react"

export default function MultiTraceChart({
  series = [],
  width = 640,
  height = 360,
  padding = 40,
  title = "",
  titleLines = null,           
  xUnit = "h",
  yUnit = "a.u.",
  legendColumns = 1,
}) {

  // detect empty/invalid series but don't return early — hooks must run
  const noSeries = !Array.isArray(series) || series.length === 0;

  const allX = Array.isArray(series) ? series.flatMap(s => s.time ?? []) : [];
  const allY = Array.isArray(series) ? series.flatMap(s => s.conc ?? []) : [];
  const xmin = allX.length ? Math.min(...allX) : 0;
  const xmax = allX.length ? Math.max(...allX) : 1;
  const ymin = 0;
  const ymax = allY.length ? Math.max(1e-9, Math.max(...allY)) : 1;

  // --- axis tick helpers ---
  const niceNum = (range, round) => {
    const exp = Math.floor(Math.log10(range || 1));
    const f = (range || 1) / Math.pow(10, exp);
    let nf;
    if (round) {
      if (f < 1.5) nf = 1;
      else if (f < 3) nf = 2;
      else if (f < 7) nf = 5;
      else nf = 10;
    } else {
      if (f <= 1) nf = 1;
      else if (f <= 2) nf = 2;
      else if (f <= 5) nf = 5;
      else nf = 10;
    }
    return nf * Math.pow(10, exp);
  };
  const niceExtent = (min, max, tickCount = 5) => {
    if (!(isFinite(min) && isFinite(max))) return {min:0, max:1, step:1};
    if (min === max) { // expand degenerate domain
      const eps = Math.abs(min) || 1;
      min -= eps * 0.5; max += eps * 0.5;
    }
    const range = max - min;
    const step = niceNum(range / Math.max(1, tickCount - 1), true);
    const niceMin = Math.floor(min / step) * step;
    const niceMax = Math.ceil(max / step) * step;
    return { min: niceMin, max: niceMax, step };
  };
  const tickValues = ({min, max, step}) => {
    const out = [];
    const n = Math.max(1, Math.round((max - min) / (step || 1)));
    for (let i = 0; i <= n; i++) out.push(Number((min + i * step).toFixed(12)));
    return out;
  };
  const fmtTick = (v, stepGuess=1) => {
    const s = Math.abs(stepGuess);
    const d = s >= 1 ? 0 : s >= 0.1 ? 1 : s >= 0.01 ? 2 : 3;
    return v.toFixed(d).replace(/\.0+$/,'').replace(/(\.\d*?)0+$/,'$1');
  };

  const xNice = niceExtent(xmin, xmax, 6);
  const yNiceBase = niceExtent(ymin, ymax, 6);
  const yNice = {
    min: Math.min(0, yNiceBase.min),
    max: yNiceBase.max,
    step: yNiceBase.step
  };
  const xTicks = tickValues(xNice);
  const yTicks = tickValues(yNice);


  const headerLines =
    (Array.isArray(titleLines) && titleLines.length)
      ? titleLines
      : (Array.isArray(title) && title.length)
        ? title
        : (title ? [title] : (series.length ? ["Regimen comparison"] : []));
  // Font sizes per line (px)
  const headerLineSizes = headerLines.map((_, i) => (i === 0 ? 14 : 12));
  const lineGap = 4; // px space between lines
  const headerBlockH = headerLines.length
    ? headerLines.reduce((sum, _, i) => sum + headerLineSizes[i] + (i ? lineGap : 0), 0)
    : 0;
  const headerPadY = 10; // top padding above the first line
  const headerH = headerLines.length ? headerPadY + headerBlockH : 0;
  const yLabelSpace = 28; // room for rotated Y label on the left
  const legendRowH = 20;  // row height per legend item
  const innerW = width - (2 * padding + yLabelSpace);
  const legendCols = Math.min(2, Math.max(1, Math.round(legendColumns)));
  const colGap = 24;
  const legendCellW = Math.max(80, (innerW - 20 - (legendCols - 1) * colGap) / legendCols);
  const legendRows = Math.ceil(series.length / legendCols);
  const legendH = series.length ? legendRows * legendRowH + 10 : 0;

  const plotLeft   = padding + yLabelSpace;
  const plotRight  = padding;
  const plotBottom = padding;
  const plotTop    = padding + headerH + legendH;

  const ariaTitle = headerLines.join("\n");

  const sx = x =>
    plotLeft + ((x - xNice.min) / (xNice.max - xNice.min || 1)) * (width - plotLeft - plotRight);
  const sy = y =>
    (height - plotBottom) -
    ((y - yNice.min) / (yNice.max - yNice.min || 1)) * (height - plotBottom - plotTop);

  const palette = ["#1f77b4","#ff7f0e","#2ca02c","#d62728","#9467bd","#8c564b"];

  const paths = useMemo(
    () =>
      series.map(s => {
        const time = s.time || [];
        const conc = s.conc || [];
        const pts = time.map((x, i) => [sx(x), sy(conc[i] ?? 0)]);
        const d = pts.map((p, i) => (i ? "L" : "M") + p[0] + " " + p[1]).join(" ");
        return { label: s.label, d };
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [JSON.stringify(series), xNice.min, xNice.max, yNice.min, yNice.max]
  );

  if (noSeries) {
    return <div style={{fontSize:12, color:"#6b7280"}}>No series to display yet.</div>;
  }

  return (
    <svg width={width} height={height} role="img" aria-label={ariaTitle || "PK comparison chart"}>
      {headerLines.length ? <title>{ariaTitle}</title> : null}
      {headerLines.length ? (
        <g transform={`translate(0, ${padding})`}>
          <text x={width / 2} y={0} textAnchor="middle" fontFamily="system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif">
            {headerLines.map((line, i) => (
              <tspan
                key={i}
                x={width / 2}
                dy={i === 0 ? headerPadY + headerLineSizes[0] : headerLineSizes[i] + lineGap}
                fontSize={headerLineSizes[i]}
                fontWeight={i === 0 ? 600 : 400}
                fill={i === 0 ? "#111827" : "#475569"}
              >
                {line}
              </tspan>
            ))}
          </text>
        </g>
      ) : null}

      {/* legend band */}
      {series.length ? (
        <g>
          <rect
            x={plotLeft}
            y={padding + headerH}
            width={width - plotLeft - plotRight}
            height={legendH}
            fill="#f8fafc"
            stroke="#e5e7eb"
            rx="6"
          />

          {series.map((s, i) => {
            const col = i % legendCols;
            const row = Math.floor(i / legendCols);
            const lx = plotLeft + 10 + col * (legendCellW + colGap);
            const ly = padding + headerH + 6 + row * legendRowH;
            return (
              <g key={i} transform={`translate(${lx}, ${ly})`}>
                <rect width="14" height="3" fill={palette[i % palette.length]} />
                <text
                  x="18"
                  y="4"
                  fontSize="12"
                  dominantBaseline="hanging"
                  fill="#334155"
                >
                  {s.label ?? `Series ${i + 1}`}
                </text>
                <title>{s.label ?? `Series ${i + 1}`}</title>
              </g>
            );
          })}
        </g>
      ) : null}

      {/* gridlines */}
      <g stroke="#e5e7eb" shapeRendering="crispEdges">
        {xTicks.map((t, i) => {
          const x = sx(t);
          return (
            <line key={`gx-${i}`} x1={x} y1={plotTop} x2={x} y2={height - plotBottom} />
          );
        })}
        {yTicks.map((v, i) => {
          const y = sy(v);
          return (
            <line key={`gy-${i}`} x1={plotLeft} y1={y} x2={width - plotRight} y2={y} />
          );
        })}
      </g>

      {/* axes */}
      <line x1={plotLeft} y1={height - plotBottom} x2={width - plotRight} y2={height - plotBottom} stroke="#9ca3af" />
      <line x1={plotLeft} y1={plotTop} x2={plotLeft} y2={height - plotBottom} stroke="#9ca3af" />

      {/* ticks & tick labels */}
      <g fontSize="11" fill="#374151">
        {/* x ticks */}
        {xTicks.map((t, i) => {
          const x = sx(t);
          const isZero = Math.abs(t) < 1e-12;
          return (
            <g key={`xt-${i}`}>
              <line x1={x} y1={height - plotBottom} x2={x} y2={height - plotBottom + 6} stroke="#9ca3af" />
              <text
                x={x}
                y={height - plotBottom + 18}
                textAnchor={isZero ? "start" : "middle"} // shift the "0" a bit right of y-axis
                dx={isZero ? 3 : 0}
              >
                {fmtTick(t, xNice.step)}
              </text>
            </g>
          );
        })}
        {/* y ticks */}
        {yTicks.map((v, i) => {
          const y = sy(v);
          return (
            <g key={`yt-${i}`}>
              <line x1={plotLeft - 6} y1={y} x2={plotLeft} y2={y} stroke="#9ca3af" />
              <text x={plotLeft - 8} y={y + 3} textAnchor="end">
                {fmtTick(v, yNice.step)}
              </text>
            </g>
          );
        })}
      </g>

      {/* labels with units */}
      <text x={width / 2} y={height - 8} textAnchor="middle" fontSize="12">Time ({xUnit})</text>
      <text
        fontSize="12"
        textAnchor="middle"
        transform={`translate(${padding - 4}, ${(height - plotBottom + plotTop) / 2}) rotate(-90)`}
      >
        Conc ({yUnit})
      </text>

      {/* paths */}
      {paths.map((p, i) => (
        <path key={i} d={p.d} fill="none" strokeWidth="2" strokeOpacity="0.95" stroke={palette[i % palette.length]} />
      ))}
    </svg>
  );
}