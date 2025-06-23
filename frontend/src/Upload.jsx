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
