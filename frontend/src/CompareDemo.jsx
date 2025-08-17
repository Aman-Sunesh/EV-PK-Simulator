import React, { useState } from "react";
import { runWhatIfBatch } from "./whatIf";
import MultiTraceChart from "./MultiTraceChart";

export default function CompareDemo() {
  const [series, setSeries] = useState([]);
  const [text, setText] = useState(JSON.stringify([
    {
      label: "100 mg q8h",
      model: "1c",
      route: "iv_bolus",
      params: { Vd: 40, kel: 0.2 },
      tau: 8, count: 6, start: 0, t_end: 48, dt: 0.1,
      dose_spec: { dose_mg: 100 }
    },
    {
      label: "150 mg q8h",
      model: "1c",
      route: "iv_bolus",
      params: { Vd: 40, kel: 0.2 },
      tau: 8, count: 6, start: 0, t_end: 48, dt: 0.1,
      dose_spec: { dose_mg: 150 }
    },
    {
      label: "2 mg/kg q8h (70 kg)",
      model: "1c",
      route: "iv_bolus",
      params: { Vd: 40, kel: 0.2 },
      tau: 8, count: 6, start: 0, t_end: 48, dt: 0.1,
      dose_spec: { dose_mg_per_kg: 2 }, weight_kg: 70
    },
    {
      label: "Optimize to Cmax_ss=10",
      model: "1c",
      route: "iv_bolus",
      params: { Vd: 40, kel: 0.2 },
      tau: 8, count: 6, start: 0, t_end: 48, dt: 0.1,
      dose_spec: { dose_mg: 100 },
      optimize: { target_Cmax_ss: 10 }
    }
  ], null, 2));

  async function compare() {
    let scenarios;
    try {
      scenarios = JSON.parse(text);
      if (!Array.isArray(scenarios)) throw new Error("JSON must be an array");
    } catch (e) {
      alert(`Invalid JSON: ${e.message}`);
      return;
    }
    const res = await runWhatIfBatch(scenarios);
    const ok = (res.results || []).filter(r => r.ok);
    setSeries(ok.map(r => ({
      label: r.label,
      time: r.result.time,
      conc: r.result.conc,
    })));
    const bad = (res.results || []).filter(r => !r.ok);
    if (bad.length) {
      console.warn("Some scenarios failed:", bad);
      alert(`Some scenarios failed:\n${bad.map(b => `${b.label}: ${b.error}`).join("\n")}`);
    }
  }

  return (
    <div className="p-4" style={{maxWidth: 860, margin: "0 auto"}}>
      <h3>Compare Regimens (editable JSON)</h3>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={14}
        style={{ width: "100%", fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" }}
      />
      <div style={{ marginTop: 8 }}>
        <button onClick={compare}>Run Comparison</button>
      </div>
      {series.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <MultiTraceChart series={series} />
        </div>
      )}
    </div>
  );
}
