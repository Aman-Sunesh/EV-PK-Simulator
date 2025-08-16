// src/Upload.jsx
import { useCallback, useState, useEffect } from "react";
import { useDropzone } from "react-dropzone";
import axios from "axios";

export default function Upload() {
  const [data, setData]     = useState([]);
  const [rawData, setRawData] = useState([]); 
  const [warnings, setWarnings] = useState([]);
  const [fitParams, setFitParams] = useState(null);
  const [dose, setDose] = useState(100.0);  // ← dose state
  const [species, setSpecies] = useState("Mus musculus");
  const [studies, setStudies]   = useState([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [selectedStudy, setSelectedStudy] = useState("");

  // Route Explorer (one-compartment) state
  const [rxRoute, setRxRoute] = useState("iv_bolus");      // iv_bolus | iv_infusion | oral | sc
  const [useFitParams, setUseFitParams] = useState(true);  // use fitted Vd/kel if available
  const [Vd, setVd] = useState(40.0);
  const [kel, setKel] = useState(0.2);
  const [ka, setKa] = useState(1.0);
  const [F, setF] = useState(1.0);
  const [Tinf, setTinf] = useState(1.0);
  const [tEnd, setTEnd] = useState(24.0);
  const [dt, setDt] = useState(0.1);
  // Dosing schedule
  const [repeatTau, setRepeatTau] = useState(8.0);
  const [repeatCount, setRepeatCount] = useState(3);
  const [repeatDose, setRepeatDose] = useState(100.0);
  const [repeatStart, setRepeatStart] = useState(0.0);
  const [schedule, setSchedule] = useState([]); // [{time, dose, Tinf?}]
  // Simulation result
  const [sim, setSim] = useState(null); // {time, conc, summary, dosing}

  // Mechanistic two-compartment parameters
  const [k10, setK10] = useState(0.0);
  const [k12, setK12] = useState(0.0);
  const [k21, setK21] = useState(0.0);
  const [V1,  setV1]  = useState(1.0);
  const [V2,  setV2]  = useState(1.0);


  // 1) Upload handler
const onDrop = useCallback(async (files) => {
  setFitParams(null);
  const form = new FormData();
  form.append("file", files[0]);

  try {
    const res = await axios.post("/upload", form);
    setRawData(res.data.data);          // store full dataset
    setData(res.data.data.slice(0,5));  // keep first 5 for preview
    setWarnings(res.data.warnings);
  } catch (err) {
    console.error("Upload error detail:", err);
    alert("Upload failed: " + (err.response?.data?.detail || err.message));
  }
}, []);

  const { getRootProps, getInputProps } = useDropzone({ onDrop });

  // load manifest on mount
  useEffect(() => {
    axios.get("/studies")
      .then(res => setStudies(res.data))
      .catch(err => console.error("Failed to fetch studies", err));
  }, []);

  // handler when user picks an example study
  const loadStudy = async id => {
    setFitParams(null);
    setSelectedStudy(id);
    try {
      const df = await axios.get(`/studies/${id}`);
      setRawData(df.data);
      setData(df.data.slice(0,5));
      // derive defaults from first row
      setSpecies(df.data[0].species || species);
      setDose(df.data[0].dose || dose);
      setWarnings([]);
    } catch (err) {
      alert("Failed to load study: " + id);
    }
  };

  // 2) Fit button
  const runFit = async () => {
    console.log("runFit called; selectedModel =", selectedModel);
    if (!rawData.length) {
      alert("Upload first");
      return;
    }
    if (!["one","two"].includes(selectedModel)) {
      alert("Please select One or Two compartment first.");
      return;
    }
    const endpoint = selectedModel === "one"
      ? "/fit/one_compartment"
      : "/fit/two_compartment";
    console.log("Hitting endpoint:", endpoint);

    try {
      const res = await axios.post(endpoint, { data: rawData, dose });
      setFitParams(res.data.results);
    } catch (err) {
      alert("Fit error: " + (err.response?.data?.detail || err.message));
    }
  };

  // 3) Report button
  const downloadReport = async () => {
    if (!rawData.length) return alert("Upload first");
    const metadata = {
      study_id: "UserStudy1",
      species, 
      route: "IV bolus",
      dose,  // use current dose
      model: selectedModel,
      k10,
      k12,
      k21,
      V1,
      V2
    };
    try {
      const res = await axios.post(
        "/report",
        { data: rawData, metadata },
        { responseType: "blob" }
      );
      const blob = new Blob([res.data], { type: "application/pdf" });
      const url  = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "EVPK_Report.pdf";
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch (err) {
      alert("Report error: " + err.message);
    }
  };

  // If using fit params, auto-fill Vd/kel when fit results arrive
  useEffect(() => {
    if (useFitParams && Array.isArray(fitParams) && fitParams.length > 0) {
      const first = fitParams[0];
      if (selectedModel === "one" && first?.fit?.Vd && first?.fit?.kel) {
        setVd(Number(first.fit.Vd));
        setKel(Number(first.fit.kel));
      }
    }
  }, [fitParams, useFitParams, selectedModel]);

  // Generate a repeated schedule (overwrites manual schedule)
  const makeRepeatSchedule = useCallback(() => {
    const rows = [];
    for (let i = 0; i < repeatCount; i++) {
      const entry = { time: repeatStart + i * repeatTau, dose: repeatDose };
      if (rxRoute === "iv_infusion") entry.Tinf = Tinf;
      rows.push(entry);
    }
    setSchedule(rows);
  }, [repeatStart, repeatTau, repeatCount, repeatDose, rxRoute, Tinf]);

  // Add a manual dose row
  const addDoseRow = () => {
    const lastTime = schedule.length ? schedule[schedule.length - 1].time : 0;
    const next = { time: lastTime, dose: repeatDose };
    if (rxRoute === "iv_infusion") next.Tinf = Tinf;
    setSchedule([...schedule, next]);
  };
  const updateDoseRow = (idx, key, val) => {
    const copy = schedule.slice();
    copy[idx] = { ...copy[idx], [key]: val };
    setSchedule(copy);
  };
  const removeDoseRow = (idx) => {
    const copy = schedule.slice();
    copy.splice(idx, 1);
    setSchedule(copy);
  };

  // Call backend /simulate_pk
  const runSim = async () => {
    const params = { Vd: Number(Vd), kel: Number(kel) };
    if (rxRoute === "oral" || rxRoute === "sc") {
      params.F = Number(F);
      params.ka = Number(ka);
    }
    if (rxRoute === "iv_infusion") {
      params.Tinf = Number(Tinf);
    }
    const body = {
      model: "1c",
      route: rxRoute,
      params,
      dosing: schedule.length ? schedule : undefined,
      repeat: schedule.length ? undefined : {
        start: Number(repeatStart),
        tau: Number(repeatTau),
        count: Number(repeatCount),
        dose: Number(repeatDose),
        Tinf: rxRoute === "iv_infusion" ? Number(Tinf) : undefined
      },
      t_end: Number(tEnd),
      dt: Number(dt)
    };
    try {
      const res = await axios.post("/simulate_pk", body);
      setSim(res.data);
    } catch (err) {
      alert("Sim error: " + (err.response?.data?.detail || err.message));
    }
  };

  // Simple SVG plot
  const Plot = ({ time, conc, width=700, height=300, margin=40 }) => {
    if (!time || !conc || time.length !== conc.length || time.length === 0) return null;
    const tmin = Math.min(...time), tmax = Math.max(...time);
    const cmin = 0, cmax = Math.max(...conc) * 1.1 || 1;
    const x = t => margin + (t - tmin) * (width - 2*margin) / (tmax - tmin || 1);
    const y = c => height - margin - (c - cmin) * (height - 2*margin) / (cmax - cmin || 1);
    const pts = time.map((t,i) => `${x(t)},${y(conc[i])}`).join(" ");
    return (
      <svg width={width} height={height} className="pk-chart">
        {/* axes */}
        <line x1={margin} y1={height-margin} x2={width-margin} y2={height-margin} stroke="#888"/>
        <line x1={margin} y1={margin} x2={margin} y2={height-margin} stroke="#888"/>
        {/* curve */}
        <polyline fill="none" stroke="#007bff" strokeWidth="2" points={pts}/>
        {/* dose ticks */}
        {Array.isArray(sim?.dosing) && sim.dosing.map((d, i) => (
          <line key={i} x1={x(d.time)} x2={x(d.time)} y1={height-margin} y2={margin} stroke="#bbb" strokeDasharray="3 4"/>
        ))}
        {/* labels */}
        <text x={width/2} y={height-8} textAnchor="middle" fontSize="12">Time (h)</text>
        <text x={16} y={margin-10} fontSize="12">Conc</text>
      </svg>
    );
  };

  return (
    <div className="container">
      <h1>PB–PK Simulator</h1>

      {!selectedModel && (
        <div className="model-select">
          <button onClick={() => setSelectedModel("one")}>
            One-Compartment Model
          </button>
          <button onClick={() => {
            console.log("Model button clicked—setting to TWO");
            setSelectedModel("two");}}>
            Two-Compartment Model
          </button>
        </div>
      )}

      {selectedModel && (
        <>
          <h2>
            {selectedModel === "one"
              ? "One-Compartment Model"
              : "Two-Compartment Model"}
          </h2>

          {/* Example Study Selector */}
          <div className="input-row">
            <label>
              Load Example:&nbsp;
              <select
                value={selectedStudy}
                onChange={(e) => loadStudy(e.target.value)}
              >
                <option value="">— select study —</option>
                {studies.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {/* Species Input */}
          <div className="input-row">
            <label>
              Species:&nbsp;
              <input
                type="text"
                value={species}
                onChange={(e) => setSpecies(e.target.value)}
                placeholder="e.g. Mus musculus"
                style={{ width: 200 }}
              />
            </label>
          </div>

          {/* Dose Input */}
          <div className="input-row">
            <label>
              Dose:&nbsp;
              <input
                type="number"
                value={dose}
                onChange={(e) => setDose(parseFloat(e.target.value))}
                style={{ width: 80 }}
              />
              &nbsp;mg
            </label>
          </div>

          {/* Mechanistic parameters (only needed for two-compartment) */}
          {selectedModel === "two" && (
            <>
              <div className="input-row">
                <label>k₁₀:&nbsp;
                  <input
                    type="number"
                    value={k10}
                    onChange={e => setK10(parseFloat(e.target.value))}
                    style={{ width: 80 }}
                  />
                </label>
                &nbsp;
                <label>k₁₂:&nbsp;
                  <input
                    type="number"
                    value={k12}
                    onChange={e => setK12(parseFloat(e.target.value))}
                    style={{ width: 80 }}
                  />
                </label>
                &nbsp;
                <label>k₂₁:&nbsp;
                  <input
                    type="number"
                    value={k21}
                    onChange={e => setK21(parseFloat(e.target.value))}
                    style={{ width: 80 }}
                  />
                </label>
              </div>
              <div className="input-row">
                <label>V₁:&nbsp;
                  <input
                    type="number"
                    value={V1}
                    onChange={e => setV1(parseFloat(e.target.value))}
                    style={{ width: 80 }}
                  />
                </label>
                &nbsp;
                <label>V₂:&nbsp;
                  <input
                    type="number"
                    value={V2}
                    onChange={e => setV2(parseFloat(e.target.value))}
                    style={{ width: 80 }}
                  />
                </label>
              </div>
            </>
          )}


          {/* File Dropzone */}
          <div {...getRootProps()} className="dropzone">
            <input {...getInputProps()} />
            <p>Drag &amp; drop CSV/Excel here, or click to select</p>
          </div>

          {warnings.length > 0 && (
            <div className="warnings">
              {warnings.map((w, i) => (
                <div key={i}>{w}</div>
              ))}
            </div>
          )}

          {/* Preview + Buttons */}
          {data.length > 0 && (
            <div className="preview-section">
              <h3>Data Preview</h3>
              <table className="preview-table">
                <thead>
                  <tr>
                    {Object.keys(data[0]).map((col) => (
                      <th key={col}>{col}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.map((row, i) => (
                    <tr key={i}>
                      {Object.values(row).map((val, j) => (
                        <td key={j}>{val}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="buttons">
                <button onClick={runFit}>
                  {selectedModel === "one"
                    ? "Fit One-Compartment"
                    : "Fit Two-Compartment"}
                </button>
                <button onClick={downloadReport}>
                  Download PDF Report
                </button>
              </div>
            </div>
          )}

          <div className="preview-section">
            <h3>Route Explorer (One-Compartment)</h3>

            <div className="input-row">
              <label>
                Route:&nbsp;
                <select value={rxRoute} onChange={e => setRxRoute(e.target.value)}>
                  <option value="iv_bolus">IV bolus</option>
                  <option value="iv_infusion">IV infusion (short-term)</option>
                  <option value="oral">Oral (first-order)</option>
                  <option value="sc">Subcutaneous (first-order)</option>
                </select>
              </label>
              &nbsp;&nbsp;
              <label>
                Use fitted Vd, kel:&nbsp;
                <input type="checkbox" checked={useFitParams} onChange={e=>setUseFitParams(e.target.checked)} />
              </label>
            </div>

            <div className="input-row">
              <label>Vd:&nbsp;
                <input type="number" value={Vd} onChange={e=>setVd(parseFloat(e.target.value))} style={{width:90}}/>
              </label>
              &nbsp;
              <label>kel:&nbsp;
                <input type="number" value={kel} onChange={e=>setKel(parseFloat(e.target.value))} style={{width:90}}/>
              </label>
              {rxRoute === "iv_infusion" && (
                <>
                  &nbsp;
                  <label>Tinf (h):&nbsp;
                    <input type="number" value={Tinf} onChange={e=>setTinf(parseFloat(e.target.value))} style={{width:90}}/>
                  </label>
                </>
              )}
              {(rxRoute === "oral" || rxRoute === "sc") && (
                <>
                  &nbsp;
                  <label>F:&nbsp;
                    <input type="number" value={F} onChange={e=>setF(parseFloat(e.target.value))} style={{width:90}}/>
                  </label>
                  &nbsp;
                  <label>ka:&nbsp;
                    <input type="number" value={ka} onChange={e=>setKa(parseFloat(e.target.value))} style={{width:90}}/>
                  </label>
                </>
              )}
            </div>

            {/* Repeat rule */}
            <div className="input-row">
              <strong>Repeat rule</strong>&nbsp;
              <label>Start (h):&nbsp;
                <input type="number" value={repeatStart} onChange={e=>setRepeatStart(parseFloat(e.target.value))} style={{width:90}}/>
              </label>
              &nbsp;
              <label>Every τ (h):&nbsp;
                <input type="number" value={repeatTau} onChange={e=>setRepeatTau(parseFloat(e.target.value))} style={{width:90}}/>
              </label>
              &nbsp;
              <label># doses:&nbsp;
                <input type="number" value={repeatCount} onChange={e=>setRepeatCount(parseInt(e.target.value||"0"))} style={{width:90}}/>
              </label>
              &nbsp;
              <label>Dose (mg):&nbsp;
                <input type="number" value={repeatDose} onChange={e=>setRepeatDose(parseFloat(e.target.value))} style={{width:110}}/>
              </label>
              {rxRoute === "iv_infusion" && (
                <>
                  &nbsp;
                  <label>Tinf (h):&nbsp;
                    <input type="number" value={Tinf} onChange={e=>setTinf(parseFloat(e.target.value))} style={{width:90}}/>
                  </label>
                </>
              )}
              &nbsp;
              <button onClick={makeRepeatSchedule}>Generate</button>
            </div>

            {/* Manual schedule table */}
            <div className="input-row">
              <strong>Custom schedule</strong>&nbsp;
              <button onClick={addDoseRow}>Add dose</button>
            </div>
            {schedule.length > 0 && (
              <table className="preview-table">
                <thead>
                  <tr>
                    <th>Time (h)</th>
                    <th>Dose (mg)</th>
                    {rxRoute === "iv_infusion" && <th>Tinf (h)</th>}
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {schedule.map((row, i) => (
                    <tr key={i}>
                      <td><input type="number" value={row.time}
                          onChange={e=>updateDoseRow(i, "time", parseFloat(e.target.value))}
                          style={{width:100}}/></td>
                      <td><input type="number" value={row.dose}
                          onChange={e=>updateDoseRow(i, "dose", parseFloat(e.target.value))}
                          style={{width:100}}/></td>
                      {rxRoute === "iv_infusion" && (
                        <td><input type="number" value={row.Tinf ?? Tinf}
                            onChange={e=>updateDoseRow(i, "Tinf", parseFloat(e.target.value))}
                            style={{width:100}}/></td>
                      )}
                      <td><button onClick={()=>removeDoseRow(i)}>Remove</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {/* Time grid & simulate */}
            <div className="input-row">
              <label>t_end (h):&nbsp;
                <input type="number" value={tEnd} onChange={e=>setTEnd(parseFloat(e.target.value))} style={{width:90}}/>
              </label>
              &nbsp;
              <label>dt (h):&nbsp;
                <input type="number" value={dt} onChange={e=>setDt(parseFloat(e.target.value))} style={{width:90}}/>
              </label>
              &nbsp;
              <button onClick={runSim}>Simulate</button>
            </div>

            {/* Results */}
            {sim && (
              <div className="results">
                <h4>Simulation</h4>
                <div className="kpis">
                  <div className="kpi">Cmax: <strong>{sim.summary.Cmax.toFixed(3)}</strong></div>
                  <div className="kpi">Tmax (h): <strong>{sim.summary.Tmax.toFixed(3)}</strong></div>
                  <div className="kpi">AUC (0–t_end): <strong>{sim.summary.AUC.toFixed(3)}</strong></div>
                  {"Cmax_ss" in sim.summary && (
                    <div className="kpi">Cmax_ss: <strong>{sim.summary.Cmax_ss.toFixed(3)}</strong></div>
                  )}
                  {"Cmin_ss" in sim.summary && (
                    <div className="kpi">Cmin_ss: <strong>{sim.summary.Cmin_ss.toFixed(3)}</strong></div>
                  )}
                  {"Cavg_ss" in sim.summary && (
                    <div className="kpi">Cavg_ss: <strong>{sim.summary.Cavg_ss.toFixed(3)}</strong></div>
                  )}
                </div>
                <Plot time={sim.time} conc={sim.conc}/>
              </div>
            )}
          </div>

          {/* Results */}
          {Array.isArray(fitParams) &&
            fitParams.map((r) => (
              <div key={r.subject} className="results">
                <h4>Subject {r.subject}</h4>
                <ul>
                  {selectedModel === "one" ? (
                    <>
                      <li>Vd = {r.fit.Vd.toFixed(3)}</li>
                      <li>kel = {r.fit.kel.toFixed(3)}</li>
                    </>
                  ) : (
                    <>
                      <li>A = {r.fit.A.toFixed(3)}</li>
                      <li>α = {r.fit.alpha.toFixed(3)}</li>
                      <li>B = {r.fit.B.toFixed(3)}</li>
                      <li>β = {r.fit.beta.toFixed(3)}</li>
                    </>
                  )}
                  <li>R² = {r.gof.R2.toFixed(3)}</li>
                  <li>AIC = {r.gof.AIC.toFixed(1)}</li>
                </ul>
              </div>
            ))}
        </>
      )}
    </div>
  );
}
