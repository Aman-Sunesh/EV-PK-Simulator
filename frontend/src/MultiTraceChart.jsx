import React, { useMemo } from "react";

export default function MultiTraceChart({ series, width = 640, height = 320, padding = 40 }) {
  const allX = series.flatMap(s => s.time ?? []);
  const allY = series.flatMap(s => s.conc ?? []);
  const xmin = Math.min(...allX), xmax = Math.max(...allX);
  const ymin = 0, ymax = Math.max(1e-9, Math.max(...allY));

  const sx = x => padding + ( (x - xmin) / (xmax - xmin || 1) ) * (width - 2*padding);
  const sy = y => height - padding - ( (y - ymin) / (ymax - ymin || 1) ) * (height - 2*padding);

  const paths = useMemo(() => series.map(s => {
    const pts = (s.time || []).map((x, i) => [sx(x), sy(s.conc[i] ?? 0)]);
    const d = pts.map((p, i) => (i ? "L" : "M") + p[0] + " " + p[1]).join(" ");
    return { label: s.label, d };
  }), [series, xmin, xmax, ymin, ymax]);

  return (
    <svg width={width} height={height} role="img" aria-label="PK comparison chart">

      {/* axes */}
      <line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} stroke="#999" />
      <line x1={padding} y1={padding} x2={padding} y2={height - padding} stroke="#999" />

      {/* ticks */}
      <text x={width/2} y={height - 8} textAnchor="middle" fontSize="12">Time</text>
      <text x={10} y={padding - 10} fontSize="12">Conc</text>

      {/* paths */}
      {paths.map((p, i) => (
        <path key={i} d={p.d} fill="none" strokeWidth="2" strokeOpacity="0.9"
          stroke={["#1f77b4","#ff7f0e","#2ca02c","#d62728","#9467bd","#8c564b"][i % 7]} />
      ))}
      
      {/* legend */}
      {series.map((s, i) => (
        <g key={i} transform={`translate(${padding + i*120}, ${padding - 20})`}>
          <rect width="14" height="3"
            fill={["#1f77b4","#ff7f0e","#2ca02c","#d62728","#9467bd","#8c564b"][i % 7]} />
          <text x="18" y="4" fontSize="12">{s.label}</text>
        </g>
      ))}
    </svg>
  );
}
