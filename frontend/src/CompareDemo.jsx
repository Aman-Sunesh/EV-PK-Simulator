import React, { useRef, useState } from "react";
import { runWhatIfBatch } from "./whatIf";
import MultiTraceChart from "./MultiTraceChart";

export default function CompareDemo() {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [series, setSeries] = useState([]);
  const [chartTitleLines, setChartTitleLines] = useState(["Compare Regimens"]);
  const fileRef = useRef(null);
  // ----- Global (shared) simulation inputs -----
  const [model, setModel] = useState("1c");             
  const [route, setRoute] = useState("iv_bolus");
  const [Vd, setVd] = useState(40);
  const [kel, setKel] = useState(0.2);
  const [tau, setTau] = useState(8);
  const [count, setCount] = useState(6);
  const [start, setStart] = useState(0);
  const [tEnd, setTEnd] = useState(48);
  const [dt, setDt] = useState(0.1);
  const [Tinf, setTinf] = useState(1);

  // ----- Per-row dosing builder -----
  const [rows, setRows] = useState([
    { label: "100 mg q8h", units: "mg", dose: 100, weightKg: 70, optimize: false, target: "",
      model: "", route: "", Vd: "", kel: "", tau: "", count: "", Tinf: "" },
    { label: "150 mg q8h", units: "mg", dose: 150, weightKg: 70, optimize: false, target: "",
      model: "", route: "", Vd: "", kel: "", tau: "", count: "", Tinf: "" },
    { label: "2 mg/kg q8h (70 kg)", units: "mg/kg", dose: 2, weightKg: 70, optimize: false, target: "",
      model: "", route: "", Vd: "", kel: "", tau: "", count: "", Tinf: "" },
    { label: "Optimize to Cmax_ss=10", units: "mg", dose: 100, weightKg: 70, optimize: true, target: "10",
      model: "", route: "", Vd: "", kel: "", tau: "", count: "", Tinf: "" },
  ]);
 

  // Build a descriptive comparison title from the user-provided scenarios
  const uniq = (arr) => Array.from(new Set(arr.filter(v => v != null)));
  const routeLabel = (s) => {
    switch (s.route) {
      case "iv_bolus": return "IV bolus";
      case "iv_infusion": {
        const Tinf = s.params?.Tinf ?? s.Tinf;
        return Number.isFinite(Number(Tinf)) ? `IV infusion (${Number(Tinf)} h)` : "IV infusion";
      }
      case "oral": return "Oral";
      case "sc": return "SC";
      default: return s.route || "—";
    }
  };
  const buildCompareTitleLines = (scenarios, plottedCount = null) => {
    const n = Array.isArray(scenarios) ? scenarios.length : 0;
    const models = uniq(scenarios.map(s => s.model));
    const taus   = uniq(scenarios.map(s => s.tau));
    const counts = uniq(scenarios.map(s => s.count));
    const tends  = uniq(scenarios.map(s => s.t_end ?? s.tEnd));
    const routes = uniq(scenarios.map(routeLabel));
    const targets = uniq(scenarios
      .map(s => s.optimize?.target_Cmax_ss)
      .filter(x => typeof x === "number"));

    const modelName =
      models.length === 1
        ? (models[0] === "1c" ? "1-compartment"
          : models[0] === "2c" ? "2-compartment"
          : models[0] === "3c" ? "3-compartment"
          : models[0])
        : null;

    const line1 = "Compare Regimens";
    const line2Bits = [`${n} regimen${n !== 1 ? "s" : ""}`];
    if (modelName)           line2Bits.push(modelName);
    if (taus.length === 1)   line2Bits.push(`τ=${taus[0]} h`);
    if (counts.length === 1) line2Bits.push(`#doses=${counts[0]}`);
    if (tends.length === 1)  line2Bits.push(`t_end=${tends[0]} h`);
    const line2 = line2Bits.join(" • ");
    const line3 = routes.length ? `Routes: ${routes.join(", ")}` : "";
    const line4 = typeof plottedCount === "number" ? `Plotted: ${plottedCount}/${n}` : "";
    const line5 = targets.length === 1 ? `Target Cmax_ss: ${targets[0]}` : "";
    return [line1, line2, line3, line4, line5].filter(Boolean);
  };
  const [text, setText] = useState(JSON.stringify([
  ], null, 2));

  const normalizeRow = (r) => ({
    label: r.label ?? "Regimen",
    units: (String(r.units ?? "mg").toLowerCase() === "mg/kg") ? "mg/kg" : "mg",
    dose: Number(r.dose ?? 0),
    weightKg: Number(r.weightKg ?? r.weight_kg ?? 70),
    optimize: r.optimize === true || String(r.optimize).toLowerCase() === "true",
    target: (r.target ?? "").toString(),
    model: (r.model ?? "").toString(),
    route: (r.route ?? "").toString(),
    params: { ...(r.params || {}) },
    Vd: r.params?.Vd ?? (r.Vd ?? ""),
    kel: r.params?.kel ?? (r.kel ?? ""),
    F: r.params?.F ?? (r.F ?? ""),
    ka: r.params?.ka ?? (r.ka ?? ""),
    tau: r.tau ?? "",
    count: r.count ?? "",
    Tinf: (r.Tinf ?? r.params?.Tinf ?? r.tinf ?? ""),
  });
  const allEqual = (vals) => vals.length > 0 && vals.every(v => JSON.stringify(v) === JSON.stringify(vals[0]));
  const commonNum = (arr) => allEqual(arr) ? Number(arr[0]) : undefined;
  const importFromRows = (rowsIn=[]) => {
    const cleaned = rowsIn.map(normalizeRow);
    if (!cleaned.length) throw new Error("No rows found in JSON.");
    setRows(cleaned);
  };
  const importFromScenarios = (scenarios=[]) => {
    if (!Array.isArray(scenarios) || scenarios.length === 0) throw new Error("No scenarios found.");
    const warns = [];
    // globals: use only if consistent across scenarios; else leave as-is and warn
    const pickCommon = (getter, label, setter) => {
      const vals = scenarios.map(getter).filter(v => v !== undefined && v !== null);
      const v = allEqual(vals) ? vals[0] : undefined;
      if (v !== undefined && typeof setter === "function") setter(v);
    };
    pickCommon(s => Number(s.start),  "start",  v => setStart(Number(v)));
    pickCommon(s => Number(s.dt),     "dt",     v => setDt(Number(v)));
    pickCommon(s => Number(s.t_end ?? s.tEnd), "t_end", v => setTEnd(Number(v)));
    setErr(""); 

    // rows
    const newRows = scenarios.map(s => {
      const ds = s.dose_spec || {};
      const units = (ds.dose_mg_per_kg != null) ? "mg/kg" : "mg";
      const dose  = Number(ds.dose_mg_per_kg ?? ds.dose_mg ?? 0);
      const weightKg = Number(s.weight_kg ?? s.weightKg ?? 70);
      const opt = s.optimize && typeof s.optimize.target_Cmax_ss === "number";
      return normalizeRow({
        label: s.label,
        units,
        dose,
        weightKg,
        optimize: !!opt,
        target: opt ? String(s.optimize.target_Cmax_ss) : "",
        model: s.model,
        route: s.route,
        params: s.params,
        tau: s.tau,
        count: s.count,
        Tinf: (s.Tinf ?? s.params?.Tinf),
      });
    });
    setRows(newRows);
  };
  const handleUploadJSON = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    try {
      const text = await f.text();
      const payload = JSON.parse(text);
      if (!Array.isArray(payload)) throw new Error("Expected a JSON array.");
      const looksScenario = payload.some(it =>
        it && (it.dose_spec || it.params || it.model || it.route)
      );
      if (looksScenario) importFromScenarios(payload);
      else importFromRows(payload);
    } catch (err) {
      alert("Upload failed: " + (err?.message || "invalid JSON"));
    } finally {
      e.target.value = "";
    }
  };

  async function compare() {
    // Build scenarios honoring per-row overrides; globals are fallback
    const scenarios = rows.map(r => {
      const effModel = (r.model || model).trim();
      const effRoute = (r.route || route).trim();
      const effVd    = r.Vd === "" ? Vd : Number(r.Vd);
      const effKel   = r.kel === "" ? kel : Number(r.kel);
      const effF     = r.F === "" ? undefined : Number(r.F);
      const effKa    = r.ka === "" ? undefined : Number(r.ka);
      const effTau   = r.tau === "" ? tau : Number(r.tau);
      const effCount = r.count === "" ? count : Number(r.count);
      const effTinf  = r.Tinf === "" ? Tinf : Number(r.Tinf);


      const rawParams =
        (r.params && Object.keys(r.params).length)
          ? r.params                       // pass-through macro/micro/F/ka, etc.
          : { Vd: effVd, kel: effKel };    // fallback for 1c

      const paramsCoerced = Object.fromEntries(
        Object.entries(rawParams).map(([k,v]) => [k, Number(v)])
      );

      const base = {
        label: r.label || "Regimen",
        model: effModel || "1c",
        route: effRoute || "iv_bolus",
        params: paramsCoerced,
        tau: Number(effTau), count: Number(effCount),
        start: Number(start), t_end: Number(tEnd), dt: Number(dt),
      };

      const dose_spec = (r.units === "mg/kg")
        ? { dose_mg_per_kg: Number(r.dose || 0) }
        : { dose_mg: Number(r.dose || 0) };
      const extra = {};
     if (effRoute === "iv_infusion") {
       const tinfFromParams = r.params?.Tinf;
       const tinfEff = r.Tinf === "" ? (tinfFromParams ?? Tinf) : Number(r.Tinf);
       extra.Tinf = Number(tinfEff);
     }
      if (r.units === "mg/kg") extra.weight_kg = Number(r.weightKg || 0);
      if (r.optimize && effRoute === "iv_bolus" && (effModel || "1c") === "1c") {
        extra.optimize = { target_Cmax_ss: Number(r.target || 0) };
      }
      return { ...base, dose_spec, ...extra };
    });
    setChartTitleLines(buildCompareTitleLines(scenarios));
    setBusy(true);
    setErr("");
    try {
      const res = await runWhatIfBatch(scenarios);
      const ok = (res?.results || []).filter(r => r.ok);
      const bad = (res?.results || []).filter(r => !r.ok);
      setSeries(ok.map(r => ({
        label: r.label,
        time: r.result?.time || [],
        conc: r.result?.conc || [],
      })));
      setChartTitleLines(buildCompareTitleLines(scenarios, ok.length));
      if (bad.length) {
        setErr(`Some scenarios failed:\n${bad.map(b => `${b.label}: ${b.error || "unknown error"}`).join("\n")}`);
        console.warn("Some scenarios failed:", bad);
      }
    } catch (e) {
      setErr(e?.message || "Request failed");
    } finally {
      setBusy(false);
    }
  }
  return (
     <div className="p-4" style={{maxWidth: 920, margin: "0 auto"}}>

      {/* Shared settings */}
      <div className="input-row" style={{display:"flex",flexWrap:"wrap",gap:12}}>
        <label>Model:&nbsp;
          <select value={model} onChange={e=>setModel(e.target.value)}>
            <option value="2c">2-compartment</option>
            <option value="3c">3-compartment</option>
            <option value="1c">1-compartment</option>
          </select>
        </label>
        <label>Route:&nbsp;
          <select value={route} onChange={e=>setRoute(e.target.value)}>
            <option value="iv_bolus">IV bolus</option>
            <option value="iv_infusion">IV infusion</option>
            <option value="oral">Oral</option>
            <option value="sc">SC</option>
          </select>
        </label>
        <label>Vd (L):&nbsp;
          <input type="number" value={Vd} onChange={e=>setVd(+e.target.value)} style={{width:90}}/>
        </label>
        <label>kel (1/h):&nbsp;
          <input type="number" value={kel} step="0.01" onChange={e=>setKel(+e.target.value)} style={{width:90}}/>
        </label>
        <label>τ (h):&nbsp;
          <input type="number" value={tau} step="0.5" onChange={e=>setTau(+e.target.value)} style={{width:80}}/>
        </label>
        <label>#doses:&nbsp;
          <input type="number" value={count} onChange={e=>setCount(+e.target.value)} style={{width:80}}/>
        </label>
        <label>t_end (h):&nbsp;
          <input type="number" value={tEnd} onChange={e=>setTEnd(+e.target.value)} style={{width:90}}/>
        </label>
        <label>dt (h):&nbsp;
          <input type="number" value={dt} step="0.01" onChange={e=>setDt(+e.target.value)} style={{width:80}}/>
        </label>
        {route==="iv_infusion" && (
          <label>Tinf (h):&nbsp;
            <input type="number" value={Tinf} step="0.1" onChange={e=>setTinf(+e.target.value)} style={{width:90}}/>
          </label>
        )}
      </div>

      {/* Regimen rows */}
      <div style={{marginTop:10}}>
        <table className="preview-table" style={{width:"100%"}}>
          <thead>
            <tr>
              <th style={{width:"22%"}}>Label</th>
              <th>Model</th>
              <th>Route</th>
              <th>Vd (L)</th>
              <th>kel (1/h)</th>
              <th>τ (h)</th>
              <th>#doses</th>
              <th>Tinf (h)</th>
              <th>Units</th>
              <th>Dose</th>
              <th>Weight (kg)</th>
              <th>Optimize Cmax_ss</th>
              <th>Advanced</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r,i)=>(
              <tr key={i}>
                <td><input value={r.label} onChange={e=>{
                      const c=[...rows]; c[i]={...c[i],label:e.target.value}; setRows(c);
                    }} style={{width:"100%"}}/></td>
                <td>
                  <select value={r.model} onChange={e=>{
                    const c=[...rows]; c[i]={...c[i],model:e.target.value}; setRows(c);
                  }}>
                    <option value="">(inherit)</option>
                    <option value="1c">1-compartment</option>
                    <option value="2c">2-compartment</option>
                    <option value="3c">3-compartment</option>
                  </select>
                </td>
                <td>
                  <select value={r.route} onChange={e=>{
                    const c=[...rows]; c[i]={...c[i],route:e.target.value}; setRows(c);
                  }}>
                    <option value="">(inherit)</option>
                    <option value="iv_bolus">IV bolus</option>
                    <option value="iv_infusion">IV infusion</option>
                    <option value="oral" disabled>Oral</option>
                    <option value="sc" disabled>SC</option>
                  </select>
                </td>
                <td>
                  <input type="number" placeholder={String(Vd)}
                    value={r.Vd} onChange={e=>{
                      const c=[...rows]; c[i]={...c[i],Vd:e.target.value}; setRows(c);
                    }} style={{width:90}}/>
                </td>
                <td>
                  <input type="number" step="0.01" placeholder={String(kel)}
                    value={r.kel} onChange={e=>{
                      const c=[...rows]; c[i]={...c[i],kel:e.target.value}; setRows(c);
                    }} style={{width:90}}/>
                </td>
                <td>
                  <input type="number" step="0.5" placeholder={String(tau)}
                    value={r.tau} onChange={e=>{
                      const c=[...rows]; c[i]={...c[i],tau:e.target.value}; setRows(c);
                    }} style={{width:80}}/>
                </td>
                <td>
                  <input type="number" placeholder={String(count)}
                    value={r.count} onChange={e=>{
                      const c=[...rows]; c[i]={...c[i],count:e.target.value}; setRows(c);
                    }} style={{width:80}}/>
                </td>
                <td>
                  {((r.route || route) === "iv_infusion") ? (
                    <input type="number" step="0.1" placeholder={String(Tinf)}
                      value={r.Tinf} onChange={e=>{
                        const c=[...rows]; c[i]={...c[i],Tinf:e.target.value}; setRows(c);
                      }} style={{width:80}}/>
                  ) : <span style={{color:"#888"}}>—</span>}
                </td>
                <td>
                  <select value={r.units} onChange={e=>{
                    const c=[...rows]; c[i]={...c[i],units:e.target.value}; setRows(c);
                  }}>
                    <option value="mg">mg</option>
                    <option value="mg/kg">mg/kg</option>
                  </select>
                </td>
                <td><input type="number" value={r.dose} onChange={e=>{
                      const c=[...rows]; c[i]={...c[i],dose:+e.target.value}; setRows(c);
                    }} style={{width:90}}/></td>
                <td>
                  <input type="number" disabled={r.units!=="mg/kg"} value={r.weightKg}
                    onChange={e=>{const c=[...rows]; c[i]={...c[i],weightKg:+e.target.value}; setRows(c);}}
                    style={{width:90}}/>
                </td>
                <td>
                  <label style={{display:"flex",gap:6,alignItems:"center"}}>
                    <input type="checkbox" checked={r.optimize}
                      onChange={e=>{const c=[...rows]; c[i]={...c[i],optimize:e.target.checked}; setRows(c);}}/>
                    <input type="number" placeholder="target" value={r.target}
                      disabled={!r.optimize || ( (r.route||route)!=="iv_bolus") || ((r.model||model)!=="1c")}
                      onChange={e=>{const c=[...rows]; c[i]={...c[i],target:e.target.value}; setRows(c);}}
                      style={{width:80}}/>
                  </label>
                </td>
                <td>
                  <details>
                    <summary>edit…</summary>
                    <div style={{display:"grid", gridTemplateColumns:"repeat(3, minmax(120px,1fr))", gap:8, marginTop:6}}>
                      <label>Route&nbsp;
                        <select value={r.route}
                          onChange={e=>{const c=[...rows]; c[i]={...c[i],route:e.target.value}; setRows(c);}}>
                          <option value="iv_bolus">IV bolus</option>
                          <option value="iv_infusion">IV infusion</option>
                        </select>
                      </label>
                      <label>τ (h)&nbsp;
                        <input type="number" step="0.5" value={r.tau}
                          onChange={e=>{const c=[...rows]; c[i]={...c[i],tau:+e.target.value}; setRows(c);}}/>
                      </label>
                      <label>#doses&nbsp;
                        <input type="number" value={r.count}
                          onChange={e=>{const c=[...rows]; c[i]={...c[i],count:+e.target.value}; setRows(c);}}/>
                      </label>
                      <label>start (h)&nbsp;
                        <input type="number" value={r.start}
                          onChange={e=>{const c=[...rows]; c[i]={...c[i],start:+e.target.value}; setRows(c);}}/>
                      </label>
                      {(r.route ?? route) === "iv_infusion" && (
                        <label>Tinf (h)&nbsp;
                          <input type="number" step="0.1" value={r.Tinf}
                            onChange={e=>{const c=[...rows]; c[i]={...c[i],Tinf:+e.target.value}; setRows(c);}}/>
                        </label>
                      )}
                    </div>
                  </details>
                </td>
                <td>
                  <button onClick={()=>{const c=rows.slice(); c.splice(i,1); setRows(c);}}>Remove</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{marginTop:8, display:"flex", gap:8}}>
          <button onClick={()=>setRows([...rows, normalizeRow({label:"New regimen", units:"mg", dose:100, weightKg:70, optimize:false, target:"", route, tau, count, start, Tinf})])}>+ Add regimen</button>
          <button onClick={()=>setRows([
            normalizeRow({ label:"100 mg q8h", units:"mg", dose:100, weightKg:70, route, tau, count, start, Tinf }),
            normalizeRow({ label:"150 mg q8h", units:"mg", dose:150, weightKg:70, route, tau, count, start, Tinf }),
            normalizeRow({ label:"2 mg/kg q8h (70 kg)", units:"mg/kg", dose:2, weightKg:70, route, tau, count, start, Tinf }),
            normalizeRow({ label:"Optimize to Cmax_ss=10", units:"mg", dose:100, weightKg:70, optimize:true, target:"10", route:"iv_bolus", tau, count, start, Tinf }),
          ])}>Load Default</button>
          <button onClick={()=>fileRef.current?.click()}>Upload JSON…</button>
          <input
            ref={fileRef}
            type="file"
            accept="application/json,.json"
            onChange={handleUploadJSON}
            style={{display:"none"}}
          />
          <button onClick={compare} disabled={busy}>{busy ? "Running…" : "Run Comparison"}</button>
        </div>
      </div>

      {/* Optional advanced preview of the JSON we will send */}
      <details style={{marginTop:10}}>
        <summary>Advanced: preview JSON payload</summary>
        <pre style={{whiteSpace:"pre-wrap"}}>
{JSON.stringify(rows.map(r=>{
  const effModel = (r.model || model).trim() || "1c";
  const effRoute = (r.route || route).trim() || "iv_bolus";
  const effVd    = r.Vd === "" ? Vd : Number(r.Vd);
  const effKel   = r.kel === "" ? kel : Number(r.kel);
  const effF     = r.F === "" ? undefined : Number(r.F);
  const effKa    = r.ka === "" ? undefined : Number(r.ka);
  const effTau   = r.tau === "" ? tau : Number(r.tau);
  const effCount = r.count === "" ? count : Number(r.count);
  const effTinf  = r.Tinf === "" ? Tinf : Number(r.Tinf);
  const rawParams =
    (r.params && Object.keys(r.params).length)
      ? r.params
      : { Vd: effVd, kel: effKel };
  const paramsCoerced = Object.fromEntries(
    Object.entries(rawParams).map(([k,v]) => [k, Number(v)])
  );
  return {
   label: r.label, model: effModel, route: effRoute,
   params: paramsCoerced,
    tau: effTau, count: effCount, start, t_end: tEnd, dt,
   ...(effRoute==="iv_infusion"
      ? { Tinf: (r.Tinf === "" ? (r.params?.Tinf ?? Tinf) : Number(r.Tinf)) }
      : {}),
    dose_spec: r.units==="mg" ? {dose_mg:r.dose} : {dose_mg_per_kg:r.dose},
    ...(r.units==="mg/kg" ? { weight_kg: r.weightKg } : {}),
    ...(r.optimize && effRoute==="iv_bolus" && effModel==="1c"
      ? { optimize:{ target_Cmax_ss:Number(r.target||0) } }
      : {})
  };
}), null, 2)}
        </pre>
      </details>
      {err && (
        <pre className="warnings" style={{whiteSpace:"pre-wrap", marginTop:10}}>{err}</pre>
      )}
      {series.length > 0 && (
        <div style={{ marginTop: 16, overflowX: "auto" }}>
          <MultiTraceChart
            titleLines={chartTitleLines}
            series={series}
            width={1000}
            height={520}
          />
        </div>
      )}
    </div>
  );
}
