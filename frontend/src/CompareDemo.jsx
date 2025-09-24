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
  const [F, setF] = useState(1.0);
  const [ka, setKa] = useState(1.0);
  const [tau, setTau] = useState(8);
  const [count, setCount] = useState(6);
  const [start, setStart] = useState(0);
  const [tEnd, setTEnd] = useState(48);
  const [dt, setDt] = useState(0.1);
  const [Tinf, setTinf] = useState(1);

  // ----- Per-row dosing builder -----
  const [rows, setRows] = useState([
    { label: "100 mg q8h", units: "mg", dose: 100, weightKg: 70, optimize: false, target: "",
      model: "", route: "", paramMode: "macro",
      // 1c micro
      Vd: "", kel: "",
      // absorption
      F: "", ka: "",
      // 2c macro
      A: "", alpha: "", B: "", beta: "",
      // 2c micro
      k10: "", k12: "", k21: "", V1: "",
      // 3c macro
      A3: "", alpha3: "", B3: "", beta3: "", C3: "", gamma3: "",
      // 3c micro
      k103: "", k123: "", k213: "", k133: "", k313: "", V13: "", V23: "", V33: "",
      tau: "", count: "", Tinf: "" },
    { label: "150 mg q8h", units: "mg", dose: 150, weightKg: 70, optimize: false, target: "",
      model: "", route: "", paramMode: "macro",
      Vd: "", kel: "", F: "", ka: "",
      A: "", alpha: "", B: "", beta: "",
      k10: "", k12: "", k21: "", V1: "",
      A3: "", alpha3: "", B3: "", beta3: "", C3: "", gamma3: "",
      k103: "", k123: "", k213: "", k133: "", k313: "", V13: "", V23: "", V33: "",
      tau: "", count: "", Tinf: "" },
    { label: "2 mg/kg q8h (70 kg)", units: "mg/kg", dose: 2, weightKg: 70, optimize: false, target: "",
      model: "", route: "", paramMode: "macro",
      Vd: "", kel: "", F: "", ka: "",
      A: "", alpha: "", B: "", beta: "",
      k10: "", k12: "", k21: "", V1: "",
      A3: "", alpha3: "", B3: "", beta3: "", C3: "", gamma3: "",
      k103: "", k123: "", k213: "", k133: "", k313: "", V13: "", V23: "", V33: "",
      tau: "", count: "", Tinf: "" },
    { label: "Optimize to Cmax_ss=10", units: "mg", dose: 100, weightKg: 70, optimize: true, target: "10",
      model: "1c", route: "iv_bolus", paramMode: "macro",
      Vd: "", kel: "", F: "", ka: "",
      A: "", alpha: "", B: "", beta: "",
      k10: "", k12: "", k21: "", V1: "",
      A3: "", alpha3: "", B3: "", beta3: "", C3: "", gamma3: "",
      k103: "", k123: "", k213: "", k133: "", k313: "", V13: "", V23: "", V33: "",
      tau: "", count: "", Tinf: "" },
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

    // param mode 
    paramMode: (r.paramMode ?? r.param_mode ?? (
      // derive from presence of micro params in uploaded JSON
      (r.params && (r.params.k10 != null || r.params.k13 != null)) ? "micro" : "macro"
    )).toString() || "macro",
    // 1c micro
    Vd: r.params?.Vd ?? (r.Vd ?? ""),
    kel: r.params?.kel ?? (r.kel ?? ""),
    // absorption (1c/2c/3c orally/SC)
    F: r.params?.F ?? (r.F ?? ""),
    ka: r.params?.ka ?? (r.ka ?? ""),
    // 2c macro
    A: r.params?.A ?? (r.A ?? ""),
    alpha: r.params?.alpha ?? (r.alpha ?? ""),
    B: r.params?.B ?? (r.B ?? ""),
    beta: r.params?.beta ?? (r.beta ?? ""),
    // 2c micro
    k10: r.params?.k10 ?? (r.k10 ?? ""),
    k12: r.params?.k12 ?? (r.k12 ?? ""),
    k21: r.params?.k21 ?? (r.k21 ?? ""),
    V1:  r.params?.V1  ?? (r.V1  ?? ""),
    // 3c macro
    A3: r.params?.A ?? (r.A3 ?? ""),
    alpha3: r.params?.alpha ?? (r.alpha3 ?? ""),
    B3: r.params?.B ?? (r.B3 ?? ""),
    beta3: r.params?.beta ?? (r.beta3 ?? ""),
    C3: r.params?.C ?? (r.C3 ?? ""),
    gamma3: r.params?.gamma ?? (r.gamma3 ?? ""),
    // 3c micro
    k103: r.params?.k10 ?? (r.k103 ?? ""),
    k123: r.params?.k12 ?? (r.k123 ?? ""),
    k213: r.params?.k21 ?? (r.k213 ?? ""),
    k133: r.params?.k13 ?? (r.k133 ?? ""),
    k313: r.params?.k31 ?? (r.k313 ?? ""),
    V13:  r.params?.V1  ?? (r.V13  ?? ""),
    V23:  r.params?.V2  ?? (r.V23  ?? ""),
    V33:  r.params?.V3  ?? (r.V33  ?? ""),

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
      // detect macro vs micro for 2c/3c
      const pm = (() => {
        const p = s.params || {};
        if (s.model === "2c" || s.model === "3c") {
          const looksMicro = ["k10","k12","k21","k13","k31","V1","V2","V3"].some(k => p[k] != null);
          return looksMicro ? "micro" : "macro";
        }
        return "macro";
      })();
      return normalizeRow({
        label: s.label,
        units,
        dose,
        weightKg,
        optimize: !!opt,
        target: opt ? String(s.optimize.target_Cmax_ss) : "",
        model: s.model,
        route: s.route,
        paramMode: pm,
        params: s.params,
        tau: s.tau,
        count: s.count,
        Tinf: (s.Tinf ?? s.params?.Tinf),
      });
    });
    setRows(newRows.map(r => pruneRowForSelection(r, { model, route })));
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
      const effF     = r.F === "" ? (["oral","sc"].includes(effRoute) ? F : undefined) : Number(r.F);
      const effKa    = r.ka === "" ? (["oral","sc"].includes(effRoute) ? ka : undefined) : Number(r.ka);
      const effTau   = r.tau === "" ? tau : Number(r.tau);
      const effCount = r.count === "" ? count : Number(r.count);
      const effTinf  = r.Tinf === "" ? Tinf : Number(r.Tinf);

      // Build params by model & param mode; row fields override params bag; fall back to globals
      let params = {};
      if ((effModel || "1c") === "1c") {
        params = { Vd: effVd, kel: effKel };
        if (["oral","sc"].includes(effRoute)) {
          if (effF != null) params.F = Number(effF);
          if (effKa != null) params.ka = Number(effKa);
        }
      } else if (effModel === "2c") {
        const pm = (r.paramMode || "macro").toLowerCase();
        if (pm === "macro") {
          params = {
            A: numPick(r.A, r.params?.A),
            alpha: numPick(r.alpha, r.params?.alpha),
            B: numPick(r.B, r.params?.B),
            beta: numPick(r.beta, r.params?.beta),
          };
        } else {
          params = {
            k10: numPick(r.k10, r.params?.k10),
            k12: numPick(r.k12, r.params?.k12),
            k21: numPick(r.k21, r.params?.k21),
            V1:  numPick(r.V1,  r.params?.V1),
            ...(r.params?.V2 != null || r.V2 != null ? { V2: numPick(r.V2, r.params?.V2) } : {})
          };
        }
        if (["oral","sc"].includes(effRoute)) {
          if (effF != null) params.F = Number(effF);
          if (effKa != null) params.ka = Number(effKa);
        }
      } else if (effModel === "3c") {
        const pm = (r.paramMode || "macro").toLowerCase();
        if (pm === "macro") {
          params = {
            A: numPick(r.A3 ?? r.A, r.params?.A),
            alpha: numPick(r.alpha3 ?? r.alpha, r.params?.alpha),
            B: numPick(r.B3 ?? r.B, r.params?.B),
            beta: numPick(r.beta3 ?? r.beta, r.params?.beta),
            C: numPick(r.C3 ?? r.C, r.params?.C),
            gamma: numPick(r.gamma3 ?? r.gamma, r.params?.gamma),
          };
        } else {
          params = {
            k10: numPick(r.k103 ?? r.k10, r.params?.k10),
            k12: numPick(r.k123 ?? r.k12, r.params?.k12),
            k21: numPick(r.k213 ?? r.k21, r.params?.k21),
            k13: numPick(r.k133 ?? r.k13, r.params?.k13),
            k31: numPick(r.k313 ?? r.k31, r.params?.k31),
            V1:  numPick(r.V13 ?? r.V1,  r.params?.V1),
            V2:  numPick(r.V23 ?? r.V2,  r.params?.V2),
            V3:  numPick(r.V33 ?? r.V3,  r.params?.V3),
          };
        }
        if (["oral","sc"].includes(effRoute)) {
          if (effF != null) params.F = Number(effF);
          if (effKa != null) params.ka = Number(effKa);
        }
      }
      // fill from r.params any missing numeric fields (conservative merge)
      if (r.params) {
        for (const [k,v] of Object.entries(r.params)) {
          if ((params[k] == null || params[k] === "") && Number.isFinite(Number(v))) {
            params[k] = Number(v);
          }
        }
      }

      const base = {
        label: r.label || "Regimen",
        model: effModel || "1c",
        route: effRoute || "iv_bolus",
        params,
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
        <label>start (h):&nbsp;
          <input
            type="number"
            value={start}
            onChange={e=>setStart(+e.target.value)}
            style={{width:90}}
          />
        </label>
        <label>t_end (h):&nbsp;
          <input
            type="number"
            value={tEnd}
            onChange={e=>setTEnd(+e.target.value)}
            style={{width:90}}
          />
        </label>
        <label>dt (h):&nbsp;
          <input
            type="number"
            value={dt}
            step="0.01"
            onChange={e=>setDt(+e.target.value)}
            style={{width:80}}
          />
        </label>
      </div>

      {/* Regimen rows */}
      <div style={{ marginTop: 10, overflowX: "auto" }}>
        <table
          className="preview-table"
          style={{ width: "100%", minWidth: 1280, tableLayout: "fixed" }}
        >
          <colgroup>
            <col style={{ width: 240 }} />  {/* Label */}
            <col style={{ width: 120 }} />  {/* Model */}
            <col style={{ width: 120 }} />  {/* Route */}
            <col style={{ width: 110 }} />  {/* Param mode */}
            <col style={{ width: 90  }} />  {/* Vd (1c) */}
            <col style={{ width: 100 }} />  {/* kel (1c) */}
            <col style={{ width: 80  }} />  {/* F (oral/sc) */}
            <col style={{ width: 80  }} />  {/* ka (oral/sc) */}
            {/* 2c macro */}
            <col style={{ width: 80  }} />  {/* A */}
            <col style={{ width: 80  }} />  {/* alpha */}
            <col style={{ width: 80  }} />  {/* B */}
            <col style={{ width: 80  }} />  {/* beta */}
            {/* 2c micro */}
            <col style={{ width: 80  }} />  {/* k10 */}
            <col style={{ width: 80  }} />  {/* k12 */}
            <col style={{ width: 80  }} />  {/* k21 */}
            <col style={{ width: 80  }} />  {/* V1 */}
            {/* 3c macro */}
            <col style={{ width: 80  }} />  {/* A3 */}
            <col style={{ width: 80  }} />  {/* alpha3 */}
            <col style={{ width: 80  }} />  {/* B3 */}
            <col style={{ width: 80  }} />  {/* beta3 */}
            <col style={{ width: 80  }} />  {/* C3 */}
            <col style={{ width: 80  }} />  {/* gamma3 */}
            {/* 3c micro */}
            <col style={{ width: 80  }} />  {/* k103 */}
            <col style={{ width: 80  }} />  {/* k123 */}
            <col style={{ width: 80  }} />  {/* k213 */}
            <col style={{ width: 80  }} />  {/* k133 */}
            <col style={{ width: 80  }} />  {/* k313 */}
            <col style={{ width: 80  }} />  {/* V13 */}
            <col style={{ width: 80  }} />  {/* V23 */}
            <col style={{ width: 80  }} />  {/* V33 */}
            <col style={{ width: 80  }} />  {/* τ */}
            <col style={{ width: 90  }} />  {/* #doses */}
            <col style={{ width: 90  }} />  {/* Tinf */}
            <col style={{ width: 85  }} />  {/* Units */}
            <col style={{ width: 100 }} />  {/* Dose */}
            <col style={{ width: 110 }} />  {/* Weight */}
            <col style={{ width: 170 }} />  {/* Optimize Cmax_ss */}
            <col style={{ width: 110 }} />  {/* Remove btn */}
          </colgroup>
            <thead>
            <tr>
              <th>Label</th>
              <th>Model</th>
              <th>Route</th>
              <th>Mode</th>
              <th>Vd (L)</th>
              <th>kel (1/h)</th>
              <th>F</th>
              <th>ka (1/h)</th>
              <th colSpan="4">2c (macro)</th>
              <th colSpan="4">2c (micro)</th>
              <th colSpan="6">3c (macro)</th>
              <th colSpan="8">3c (micro)</th>
              <th>τ (h)</th>
              <th>#doses</th>
              <th>Tinf (h)</th>
              <th>Units</th>
              <th>Dose</th>
              <th>Weight (kg)</th>
              <th>Optimize Cmax_ss</th>
              <th></th>
            </tr>
            <tr style={{fontSize:"0.8rem", color:"#666"}}>
              <th></th><th></th><th></th><th></th>
              <th>Vd</th><th>kel</th><th>F</th><th>ka</th>
              <th>A</th><th>α</th><th>B</th><th>β</th>
              <th>k10</th><th>k12</th><th>k21</th><th>V1</th>
              <th>A</th><th>α</th><th>B</th><th>β</th><th>C</th><th>γ</th>
              <th>k10</th><th>k12</th><th>k21</th><th>k13</th><th>k31</th><th>V1</th><th>V2</th><th>V3</th>
              <th>τ</th><th>#</th><th>Tinf</th><th></th><th></th><th></th><th></th><th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r,i)=>(
              <tr key={i}>
                <td><input value={r.label} onChange={e=>{
                      const c=[...rows]; c[i]={...c[i],label:e.target.value}; setRows(c);
                    }} style={{width:"100%"}}/></td>
                <td>
                  <select
                    value={r.model}
                    onChange={e=>{
                      const c=[...rows];
                      const updated = { ...c[i], model: e.target.value };
                      c[i] = pruneRowForSelection(updated, { model, route });
                      setRows(c);
                    }}
                    style={{ width: "100%", minWidth: 110, fontSize: "0.95rem", padding: "6px 8px" }}
                  >
                    <option value="">(inherit)</option>
                    <option value="1c">1-compartment</option>
                    <option value="2c">2-compartment</option>
                    <option value="3c">3-compartment</option>
                  </select>
                </td>
                <td>
                <select value={r.route} onChange={e=>{
                  const c=[...rows];
                  const updated = { ...c[i], route: e.target.value };
                  c[i] = pruneRowForSelection(updated, { model, route: e.target.value });
                  setRows(c);
                }}>
                    <option value="">(inherit)</option>
                    <option value="iv_bolus">IV bolus</option>
                    <option value="iv_infusion">IV infusion</option>
                    <option value="oral">Oral</option>
                    <option value="sc">SC</option>
                  </select>
                </td>
                {/* param mode (only 2c/3c) */}
                <td>
                <select
                  value={r.paramMode || "macro"}
                  onChange={e=>{
                    const c=[...rows];
                    const updated = { ...c[i], paramMode: e.target.value };
                    c[i] = pruneRowForSelection(updated, { model, route });
                    setRows(c);
                  }}
                  disabled={((r.model||model) === "1c")}
                    style={{ width: "100%" }}
                  >
                    <option value="macro">macro</option>
                    <option value="micro">micro</option>
                  </select>
                </td>
                <td>
                  <ParamCell
                    enabled={(r.model||model) === "1c"}
                    value={r.Vd}
                    placeholder={String(Vd)}
                    onChange={e=>{ const c=[...rows]; c[i]={...c[i],Vd:e.target.value}; setRows(c); }}
                  />
                </td>
                <td>
                  <ParamCell
                    enabled={(r.model||model) === "1c"}
                    value={r.kel}
                    placeholder={String(kel)}
                    step="0.01"
                    onChange={e=>{ const c=[...rows]; c[i]={...c[i],kel:e.target.value}; setRows(c); }}
                  />
                </td>
                {/* F / ka shown only for oral or sc */}
                <td>
                  <ParamCell
                    enabled={["oral","sc"].includes((r.route||route))}
                    value={r.F}
                    placeholder={String(F)}
                    step="0.01"
                    onChange={e=>{const c=[...rows]; c[i]={...c[i],F:e.target.value}; setRows(c);}}
                  />
                </td>
                <td>
                  <ParamCell
                    enabled={["oral","sc"].includes((r.route||route))}
                    value={r.ka}
                    placeholder={String(ka)}
                    step="0.01"
                    onChange={e=>{const c=[...rows]; c[i]={...c[i],ka:e.target.value}; setRows(c);}}
                  />
                </td>
                {/* 2c macro: A, alpha, B, beta */}
                <td><ParamCell enabled={(r.model||model)==="2c" && (r.paramMode||"macro")==="macro"} value={r.A} placeholder="A" title="2c macro: A" onChange={e=>{const c=[...rows]; c[i]={...c[i],A:e.target.value}; setRows(c);}} /></td>
                <td><ParamCell enabled={(r.model||model)==="2c" && (r.paramMode||"macro")==="macro"} value={r.alpha} placeholder="alpha" title="2c macro: alpha" onChange={e=>{const c=[...rows]; c[i]={...c[i],alpha:e.target.value}; setRows(c);}} /></td>
                <td><ParamCell enabled={(r.model||model)==="2c" && (r.paramMode||"macro")==="macro"} value={r.B}     placeholder="B"     title="2c macro: B"     onChange={e=>{const c=[...rows]; c[i]={...c[i],B:e.target.value}; setRows(c);}} /></td>
                <td><ParamCell enabled={(r.model||model)==="2c" && (r.paramMode||"macro")==="macro"} value={r.beta}  placeholder="beta"  title="2c macro: beta"  onChange={e=>{const c=[...rows]; c[i]={...c[i],beta:e.target.value}; setRows(c);}} /></td>
                {/* 2c micro: k10,k12,k21,V1 */}
                <td><ParamCell enabled={(r.model||model)==="2c" && (r.paramMode||"macro")==="micro"} value={r.k10} placeholder="k10" title="2c micro: k10" onChange={e=>{const c=[...rows]; c[i]={...c[i],k10:e.target.value}; setRows(c);}} /></td>
                <td><ParamCell enabled={(r.model||model)==="2c" && (r.paramMode||"macro")==="micro"} value={r.k12} placeholder="k12" title="2c micro: k12" onChange={e=>{const c=[...rows]; c[i]={...c[i],k12:e.target.value}; setRows(c);}} /></td>
                <td><ParamCell enabled={(r.model||model)==="2c" && (r.paramMode||"macro")==="micro"} value={r.k21} placeholder="k21" title="2c micro: k21" onChange={e=>{const c=[...rows]; c[i]={...c[i],k21:e.target.value}; setRows(c);}} /></td>
                <td><ParamCell enabled={(r.model||model)==="2c" && (r.paramMode||"macro")==="micro"} value={r.V1}  placeholder="V1"  title="2c micro: V1"  onChange={e=>{const c=[...rows]; c[i]={...c[i],V1:e.target.value};  setRows(c);}} /></td>
                {/* 3c macro */}
                <td><ParamCell enabled={(r.model||model)==="3c" && (r.paramMode||"macro")==="macro"} value={r.A3}     placeholder="A"     title="3c macro: A"     onChange={e=>{const c=[...rows]; c[i]={...c[i],A3:e.target.value}; setRows(c);}} /></td>
                <td><ParamCell enabled={(r.model||model)==="3c" && (r.paramMode||"macro")==="macro"} value={r.alpha3} placeholder="alpha" title="3c macro: alpha" onChange={e=>{const c=[...rows]; c[i]={...c[i],alpha3:e.target.value}; setRows(c);}} /></td>
                <td><ParamCell enabled={(r.model||model)==="3c" && (r.paramMode||"macro")==="macro"} value={r.B3}     placeholder="B"     title="3c macro: B"     onChange={e=>{const c=[...rows]; c[i]={...c[i],B3:e.target.value}; setRows(c);}} /></td>
                <td><ParamCell enabled={(r.model||model)==="3c" && (r.paramMode||"macro")==="macro"} value={r.beta3}  placeholder="beta"  title="3c macro: beta"  onChange={e=>{const c=[...rows]; c[i]={...c[i],beta3:e.target.value}; setRows(c);}} /></td>
                <td><ParamCell enabled={(r.model||model)==="3c" && (r.paramMode||"macro")==="macro"} value={r.C3}     placeholder="C"     title="3c macro: C"     onChange={e=>{const c=[...rows]; c[i]={...c[i],C3:e.target.value}; setRows(c);}} /></td>
                <td><ParamCell enabled={(r.model||model)==="3c" && (r.paramMode||"macro")==="macro"} value={r.gamma3} placeholder="gamma" title="3c macro: gamma" onChange={e=>{const c=[...rows]; c[i]={...c[i],gamma3:e.target.value}; setRows(c);}} /></td>

                {/* 3c micro */}
                <td><ParamCell enabled={(r.model||model)==="3c" && (r.paramMode||"macro")==="micro"} value={r.k103} placeholder="k10" title="3c micro: k10" onChange={e=>{const c=[...rows]; c[i]={...c[i],k103:e.target.value}; setRows(c);}} /></td>
                <td><ParamCell enabled={(r.model||model)==="3c" && (r.paramMode||"macro")==="micro"} value={r.k123} placeholder="k12" title="3c micro: k12" onChange={e=>{const c=[...rows]; c[i]={...c[i],k123:e.target.value}; setRows(c);}} /></td>
                <td><ParamCell enabled={(r.model||model)==="3c" && (r.paramMode||"macro")==="micro"} value={r.k213} placeholder="k21" title="3c micro: k21" onChange={e=>{const c=[...rows]; c[i]={...c[i],k213:e.target.value}; setRows(c);}} /></td>
                <td><ParamCell enabled={(r.model||model)==="3c" && (r.paramMode||"macro")==="micro"} value={r.k133} placeholder="k13" title="3c micro: k13" onChange={e=>{const c=[...rows]; c[i]={...c[i],k133:e.target.value}; setRows(c);}} /></td>
                <td><ParamCell enabled={(r.model||model)==="3c" && (r.paramMode||"macro")==="micro"} value={r.k313} placeholder="k31" title="3c micro: k31" onChange={e=>{const c=[...rows]; c[i]={...c[i],k313:e.target.value}; setRows(c);}} /></td>
                <td><ParamCell enabled={(r.model||model)==="3c" && (r.paramMode||"macro")==="micro"} value={r.V13}  placeholder="V1" title="3c micro: V1" onChange={e=>{const c=[...rows]; c[i]={...c[i],V13:e.target.value}; setRows(c);}} /></td>
                <td><ParamCell enabled={(r.model||model)==="3c" && (r.paramMode||"macro")==="micro"} value={r.V23}  placeholder="V2" title="3c micro: V2" onChange={e=>{const c=[...rows]; c[i]={...c[i],V23:e.target.value}; setRows(c);}} /></td>
                <td><ParamCell enabled={(r.model||model)==="3c" && (r.paramMode||"macro")==="micro"} value={r.V33}  placeholder="V3" title="3c micro: V3" onChange={e=>{const c=[...rows]; c[i]={...c[i],V33:e.target.value}; setRows(c);}} /></td>
                <td>
                  <input
                    type="number"
                    step="0.5"
                    placeholder={String(tau)}
                    value={r.tau}
                    onChange={e=>{
                      const c=[...rows]; c[i]={...c[i],tau:e.target.value}; setRows(c);
                    }}
                    style={{ width: "100%" }}
                  />
                </td>
                <td>
                  <input
                    type="number"
                    placeholder={String(count)}
                    value={r.count}
                    onChange={e=>{
                      const c=[...rows]; c[i]={...c[i],count:e.target.value}; setRows(c);
                    }}
                    style={{ width: "100%" }}
                  />
                </td>
                <td>
                <ParamCell
                  enabled={(r.route || route) === "iv_infusion"}
                  value={r.Tinf}
                  placeholder={String(Tinf)}
                  step="0.1"
                  onChange={e=>{ const c=[...rows]; c[i]={...c[i],Tinf:e.target.value}; setRows(c); }}
                />
                </td>
                <td>
                  <select value={r.units} onChange={e=>{
                    const c=[...rows]; c[i]={...c[i],units:e.target.value}; setRows(c);
                  }}>
                    <option value="mg">mg</option>
                    <option value="mg/kg">mg/kg</option>
                  </select>
                </td>
                <td>
                  <input
                    type="number"
                    value={r.dose}
                    onChange={e=>{
                      const c=[...rows]; c[i]={...c[i],dose:+e.target.value}; setRows(c);
                    }}
                    style={{ width: "100%" }}
                  />
                </td>
                <td>
                  <input
                    type="number"
                    disabled={r.units!=="mg/kg"}
                    value={r.weightKg}
                    onChange={e=>{
                      const c=[...rows]; c[i]={...c[i],weightKg:+e.target.value}; setRows(c);
                    }}
                    style={{ width: "100%" }}
                  />
                </td>
                <td>
                  <label style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 6, alignItems: "center" }}>
                    <input
                      type="checkbox"
                      checked={r.optimize}
                      onChange={e=>{
                        const c=[...rows]; c[i]={...c[i],optimize:e.target.checked}; setRows(c);
                      }}
                    />
                    <input
                      type="number"
                      placeholder="target"
                      value={r.target}
                      disabled={
                        !r.optimize ||
                        ((r.route||route)!=="iv_bolus") ||
                        ((r.model||model)!=="1c")
                      }
                      onChange={e=>{
                        const c=[...rows]; c[i]={...c[i],target:e.target.value}; setRows(c);
                      }}
                      style={{ width: "100%" }}
                    />
                  </label>
                </td>
                <td>
                  <button
                    onClick={()=>{const c=rows.slice(); c.splice(i,1); setRows(c);}}
                    style={{ width: "100%", minWidth: 100 }}
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{marginTop:8, display:"flex", gap:8}}>
          <button onClick={()=>setRows([...rows, normalizeRow({
            label:"New regimen", units:"mg", dose:100, weightKg:70, optimize:false, target:"",
            route, tau, count, start, Tinf, paramMode:"macro"
          })])}>+ Add regimen</button>
          <button onClick={()=>setRows([
            normalizeRow({ label:"100 mg q8h", units:"mg", dose:100, weightKg:70, route, tau, count, start, Tinf, paramMode:"macro" }),
            normalizeRow({ label:"150 mg q8h", units:"mg", dose:150, weightKg:70, route, tau, count, start, Tinf, paramMode:"macro" }),
            normalizeRow({ label:"2 mg/kg q8h (70 kg)", units:"mg/kg", dose:2, weightKg:70, route, tau, count, start, Tinf, paramMode:"macro" }),
            normalizeRow({ label:"Optimize to Cmax_ss=10", units:"mg", dose:100, weightKg:70, optimize:true, target:"10", route:"iv_bolus", tau, count, start, Tinf, paramMode:"macro" }),
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
  const effF     = r.F === "" ? (["oral","sc"].includes(effRoute) ? F : undefined) : Number(r.F);
  const effKa    = r.ka === "" ? (["oral","sc"].includes(effRoute) ? ka : undefined) : Number(r.ka);
  const effTau   = r.tau === "" ? tau : Number(r.tau);
  const effCount = r.count === "" ? count : Number(r.count);
  const effTinf  = r.Tinf === "" ? Tinf : Number(r.Tinf);
  const PM = (r.paramMode || "macro").toLowerCase();
  let params = {};
  if (effModel === "1c") {
    params = { Vd: effVd, kel: effKel };
    if (["oral","sc"].includes(effRoute)) { if (effF!=null) params.F=Number(effF); if (effKa!=null) params.ka=Number(effKa); }
  } else if (effModel === "2c") {
    params = PM === "macro"
      ? { A: Number(r.A||0), alpha: Number(r.alpha||0), B: Number(r.B||0), beta: Number(r.beta||0) }
      : { k10: Number(r.k10||0), k12: Number(r.k12||0), k21: Number(r.k21||0), V1: Number(r.V1||0) };
    if (["oral","sc"].includes(effRoute)) { if (effF!=null) params.F=Number(effF); if (effKa!=null) params.ka=Number(effKa); }
  } else {
    params = PM === "macro"
      ? { A: Number((r.A3??r.A)||0), alpha: Number((r.alpha3??r.alpha)||0), B: Number((r.B3??r.B)||0), beta: Number((r.beta3??r.beta)||0), C: Number((r.C3??r.C)||0), gamma: Number((r.gamma3??r.gamma)||0) }
      : { k10: Number((r.k103??r.k10)||0), k12: Number((r.k123??r.k12)||0), k21: Number((r.k213??r.k21)||0), k13: Number((r.k133??r.k13)||0), k31: Number((r.k313??r.k31)||0), V1: Number((r.V13??r.V1)||0), V2: Number((r.V23??r.V2)||0), V3: Number((r.V33??r.V3)||0) };
    if (["oral","sc"].includes(effRoute)) { if (effF!=null) params.F=Number(effF); if (effKa!=null) params.ka=Number(effKa); }
  }
  return {
   label: r.label, model: effModel, route: effRoute,
   params,
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

// helper: first numeric of [rowField, paramsField]
function numPick(rowV, paramsV) {
  if (rowV !== "" && rowV != null && Number.isFinite(Number(rowV))) return Number(rowV);
  if (paramsV != null && Number.isFinite(Number(paramsV))) return Number(paramsV);
  return undefined;
}

function ParamCell({ enabled, value, placeholder, step, title, onChange, style }) {
  if (!enabled) return <span style={{ color: "#888" }}>—</span>;
  return (
    <input
      type="number"
      value={value}
      placeholder={placeholder}
      step={step}
      title={title}
      onChange={onChange}
      style={{ width: "100%", ...(style || {}) }}
    />
  );
}

// when model/route/paramMode changes, blank out fields that no longer apply
function pruneRowForSelection(row, globals) {
  const effModel = (row.model || globals.model || "1c").trim();
  const effRoute = (row.route || globals.route || "iv_bolus").trim();
  const effPM    = (row.paramMode || "macro").toLowerCase();
  const is1c = effModel === "1c";
  const is2c = effModel === "2c";
  const is3c = effModel === "3c";
  const oralSC = ["oral", "sc"].includes(effRoute);

  const next = { ...row };
  // absorption only for oral/SC
  if (!oralSC) { next.F = ""; next.ka = ""; }
  // 1c only
  if (!is1c) { next.Vd = ""; next.kel = ""; }
  // 2c macro
  if (!(is2c && effPM === "macro")) { next.A = ""; next.alpha = ""; next.B = ""; next.beta = ""; }
  // 2c micro
  if (!(is2c && effPM === "micro")) { next.k10 = ""; next.k12 = ""; next.k21 = ""; next.V1 = ""; }
  // 3c macro
  if (!(is3c && effPM === "macro")) { next.A3 = ""; next.alpha3 = ""; next.B3 = ""; next.beta3 = ""; next.C3 = ""; next.gamma3 = ""; }
  // 3c micro
  if (!(is3c && effPM === "micro")) { next.k103 = ""; next.k123 = ""; next.k213 = ""; next.k133 = ""; next.k313 = ""; next.V13 = ""; next.V23 = ""; next.V33 = ""; }
  // infusion time only for iv_infusion
  if (effRoute !== "iv_infusion") { next.Tinf = ""; }
  return next;
}