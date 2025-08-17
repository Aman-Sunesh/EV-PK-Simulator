// src/Upload.jsx
import { useCallback, useState, useEffect, useMemo } from "react";
import { useDropzone } from "react-dropzone";
import axios from "axios";

export default function Upload() {
  const PRESETS = {
    "EV (IV, mouse)": {
      one:   { Vd: 0.07,  kel: Math.log(2)/2.0, F: 1.0, ka: 1.5, Tinf: 0.5, tEnd: 24 }, 
      twoM:  { A: 0.8, alpha: 0.8, B: 0.2, beta: 0.2 },                                  
      twoμ:  { k10: 0.35, k12: 0.6, k21: 0.3, V1: 0.04, V2: 0.06 },
      threeM: { A: 0.6, alpha: 1.2, B: 0.3, beta: 0.3, C: 0.1, gamma: 0.06 },
      threeμ: { k10: 0.35, k12: 0.6, k21: 0.25, k13: 0.35, k31: 0.12, V1: 0.04, V2: 0.06, V3: 0.1 }                  
    },
    "Small molecule (human)": {
      one:   { Vd: 40,    kel: 0.2,              F: 1.0, ka: 1.0, Tinf: 1.0, tEnd: 24 }, 
      twoM:  { A: 0.7, alpha: 1.0, B: 0.3, beta: 0.1 },
      twoμ:  { k10: 0.15, k12: 0.25, k21: 0.15, V1: 10,  V2: 30 },
      threeM: { A: 0.55, alpha: 0.9, B: 0.35, beta: 0.18, C: 0.10, gamma: 0.04 },
      threeμ: { k10: 0.12, k12: 0.22, k21: 0.15, k13: 0.08, k31: 0.05, V1: 12, V2: 25, V3: 40 }
    }
  };

  const PRESET_NAMES = Object.keys(PRESETS);
  const [preset, setPreset] = useState(PRESET_NAMES[0]);
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

  const [Vd, setVd] = useState(PRESETS[preset].one.Vd);
  const [kel, setKel] = useState(PRESETS[preset].one.kel);
  const [ka, setKa] = useState(PRESETS[preset].one.ka);
  const [F, setF] = useState(PRESETS[preset].one.F);
  const [Tinf, setTinf] = useState(PRESETS[preset].one.Tinf);
  const [tEnd, setTEnd] = useState(PRESETS[preset].one.tEnd);

  const [dt, setDt] = useState(0.1);
  const [logY, setLogY] = useState(false);  // semilog toggle

  // Dosing schedule (legacy table) and Program Builder
  const [repeatTau, setRepeatTau] = useState(8.0);
  const [repeatCount, setRepeatCount] = useState(3);
  const [repeatDose, setRepeatDose] = useState(100.0);
  const [repeatStart, setRepeatStart] = useState(0.0);
  const [schedule, setSchedule] = useState([]); // [{time, dose, Tinf?}]
  const [program, setProgram] = useState([]);   // high-level steps
  const [weightKg, setWeightKg] = useState(70);
  const [useMgPerKg, setUseMgPerKg] = useState(false);
  const [optTargetCmax, setOptTargetCmax] = useState("");

  // Simulation result
  const [sim, setSim] = useState(null); // {time, conc, summary, dosing}

  // Mechanistic two-compartment parameters
  const [k10, setK10] = useState(PRESETS[preset].twoμ.k10);
  const [k12, setK12] = useState(PRESETS[preset].twoμ.k12);
  const [k21, setK21] = useState(PRESETS[preset].twoμ.k21);
  const [V1,  setV1]  = useState(PRESETS[preset].twoμ.V1);
  const [V2,  setV2]  = useState(PRESETS[preset].twoμ.V2);

  // Three-compartment (macro & micro)
  const [useFitThreeMacros, setUseFitThreeMacros] = useState(true);
  const [A3, setA3] = useState(PRESETS[preset].threeM.A);
  const [alpha3, setAlpha3] = useState(PRESETS[preset].threeM.alpha);
  const [B3, setB3] = useState(PRESETS[preset].threeM.B);
  const [beta3, setBeta3] = useState(PRESETS[preset].threeM.beta);
  const [C3, setC3] = useState(PRESETS[preset].threeM.C);
  const [gamma3, setGamma3] = useState(PRESETS[preset].threeM.gamma);
  const [k103, setK103] = useState(PRESETS[preset].threeμ.k10);
  const [k123, setK123] = useState(PRESETS[preset].threeμ.k12);
  const [k213, setK213] = useState(PRESETS[preset].threeμ.k21);
  const [k133, setK133] = useState(PRESETS[preset].threeμ.k13);
  const [k313, setK313] = useState(PRESETS[preset].threeμ.k31);
  const [V13, setV13] = useState(PRESETS[preset].threeμ.V1);
  const [V23, setV23] = useState(PRESETS[preset].threeμ.V2);
  const [V33, setV33] = useState(PRESETS[preset].threeμ.V3);

  // Two-comp parametrization for simulator
  const [paramMode, setParamMode] = useState("macro"); // "macro" | "micro"
  const [useFitTwoMacros, setUseFitTwoMacros] = useState(true);

  const [A, setA] = useState(PRESETS[preset].twoM.A);
  const [alpha, setAlpha] = useState(PRESETS[preset].twoM.alpha);
  const [B, setB] = useState(PRESETS[preset].twoM.B);
  const [beta, setBeta] = useState(PRESETS[preset].twoM.beta);

  // apply preset when it changes (unless user wants fitted params)
  useEffect(() => {
    const p = PRESETS[preset];
    if (!useFitParams) {
      setVd(p.one.Vd); setKel(p.one.kel);
    }
    setF(p.one.F); setKa(p.one.ka); setTinf(p.one.Tinf); setTEnd(p.one.tEnd);
    if (!useFitTwoMacros) {
      setA(p.twoM.A); setAlpha(p.twoM.alpha); setB(p.twoM.B); setBeta(p.twoM.beta);
    }
    setK10(p.twoμ.k10); setK12(p.twoμ.k12); setK21(p.twoμ.k21); setV1(p.twoμ.V1); setV2(p.twoμ.V2);

    if (!useFitThreeMacros) 
      {
      setA3(p.threeM.A); setAlpha3(p.threeM.alpha);
      setB3(p.threeM.B); setBeta3(p.threeM.beta);
      setC3(p.threeM.C); setGamma3(p.threeM.gamma);
    }

    setK103(p.threeμ.k10); setK123(p.threeμ.k12); setK213(p.threeμ.k21);
    setK133(p.threeμ.k13); setK313(p.threeμ.k31);
    setV13(p.threeμ.V1); setV23(p.threeμ.V2); setV33(p.threeμ.V3);

  }, [preset]); // eslint-disable-line react-hooks/exhaustive-deps


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
      const rows = Array.isArray(df.data) ? df.data : [];
      setRawData(df.data);
      setData(df.data.slice(0,5));
      // derive defaults from first row
      if (rows.length > 0) 
      {
        setSpecies(rows[0].species ?? species);
        setDose(rows[0].dose ?? dose);
      }

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
    if (!["one","two","three"].includes(selectedModel)) {
      alert("Please select One, Two, or Three compartment first.");
      return;
    }

    const endpoint =
      selectedModel === "one"   ? "/fit/one_compartment" :
      selectedModel === "two"   ? "/fit/two_compartment" :
                                  "/fit/three_compartment";
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

    const routeLabel =
      rxRoute === "iv_bolus"    ? "IV bolus" :
      rxRoute === "iv_infusion" ? "IV infusion" :
      rxRoute === "oral"        ? "Oral" :
                                  "Subcutaneous";

    const metadata = {
      study_id: "UserStudy1",
      species,
      route: routeLabel,
      dose,
      model: selectedModel,
      ...(rxRoute === "iv_infusion" ? { Tinf } : {}),
      ...((rxRoute === "oral" || rxRoute === "sc") ? { F, ka } : {}),
      ...(selectedModel === "two"
        ? { k10, k12, k21, V1, V2 }
        : selectedModel === "three"
        ? { k10: k103, k12: k123, k21: k213, k13: k133, k31: k313, V1: V13, V2: V23, V3: V33 }
        : {})
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

  // If using 2c fitted macros, auto-fill A,alpha,B,beta
  useEffect(() => {
    if (useFitTwoMacros && Array.isArray(fitParams) && fitParams.length > 0) {
      const first = fitParams[0]?.fit || {};
      if (selectedModel === "two" && first?.A != null && first?.alpha != null && first?.B != null && first?.beta != null) {
        setA(Number(first.A));
        setAlpha(Number(first.alpha));
        setB(Number(first.B));
        setBeta(Number(first.beta));
      }
    }
  }, [fitParams, useFitTwoMacros, selectedModel]);


  // If using 3c fitted macros, auto-fill A,α,B,β,C,γ
  useEffect(() => {
    if (useFitThreeMacros && Array.isArray(fitParams) && fitParams.length > 0) {
      const first = fitParams[0]?.fit || {};
      if (selectedModel === "three" &&
          first?.A != null && first?.alpha != null &&
          first?.B != null && first?.beta  != null &&
          first?.C != null && first?.gamma != null) {
        setA3(Number(first.A)); setAlpha3(Number(first.alpha));
        setB3(Number(first.B)); setBeta3(Number(first.beta));
        setC3(Number(first.C)); setGamma3(Number(first.gamma));
      }
    }
  }, [fitParams, useFitThreeMacros, selectedModel]);

  // Generate a repeated schedule (overwrites manual schedule)
  const makeRepeatSchedule = useCallback(() => {
    const rows = [];
    for (let i = 0; i < repeatCount; i++) {
      const effDose = useMgPerKg ? repeatDose * weightKg : repeatDose; // mg
      const entry = { time: repeatStart + i * repeatTau, dose: effDose };
      if (rxRoute === "iv_infusion") entry.Tinf = Tinf;
      rows.push(entry);
    }
    setSchedule(rows);
  }, [repeatStart, repeatTau, repeatCount, repeatDose, rxRoute, Tinf, useMgPerKg, weightKg]);

  // Add a manual dose row
  const addDoseRow = () => {
    const lastTime = schedule.length ? schedule[schedule.length - 1].time : repeatStart;
    const nextTime = schedule.length ? lastTime + repeatTau : repeatStart;
    const effDose = useMgPerKg ? repeatDose * weightKg : repeatDose; // mg
    const next = { time: nextTime, dose: effDose };
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

  // -------- Validation / guardrails for "Simulate" --------
  const simErrors = useMemo(() => {
    const errs = [];
    // global grid checks
    if (!(tEnd > 0)) errs.push("t_end must be > 0");
    if (!(dt > 0)) errs.push("dt must be > 0");

    // route-specific
    if (rxRoute === "iv_infusion" && !(Tinf > 0)) errs.push("Tinf must be > 0 for infusion");
    if ((rxRoute === "oral" || rxRoute === "sc") && !(ka > 0)) errs.push("ka must be > 0 for oral/sc");

    // model-specific
    if (selectedModel === "one") {
      if (!(Vd > 0)) errs.push("Vd must be > 0");
      if (!(kel > 0)) errs.push("kel must be > 0");
    } 
    
    else if (selectedModel === "two") {
      if (paramMode === "macro") {
        if (!(alpha > 0 && beta > 0)) errs.push("alpha and beta must be > 0");
        const rel = Math.abs(alpha - beta) / Math.max(alpha, beta || 1);
        if (rel < 1e-2) errs.push("alpha ≈ beta; choose more distinct values");
        // A and B can be zero/non-negative; leave as-is.
      } 
      
      else {
        if (!(k10 > 0)) errs.push("k10 must be > 0");
        if (!(k12 > 0)) errs.push("k12 must be > 0");
        if (!(k21 > 0)) errs.push("k21 must be > 0");
        if (!(V1  > 0)) errs.push("V1 must be > 0");
      }

    } else if (selectedModel === "three") {
      if (paramMode === "macro") {
        if (!(alpha3 > 0 && beta3 > 0 && gamma3 > 0)) errs.push("α, β, γ must be > 0");
        const maxr = Math.max(alpha3, beta3, gamma3 || 1);
        const sep = Math.min(Math.abs(alpha3-beta3), Math.abs(alpha3-gamma3), Math.abs(beta3-gamma3)) / maxr;
        if (sep < 1e-3) errs.push("α, β, γ too close; choose more distinct values");
      } else {
        if (!(k103 > 0 && k123 > 0 && k213 > 0 && k133 > 0 && k313 > 0)) errs.push("All k's must be > 0");
        if (!(V13 > 0 && V23 > 0 && V33 > 0)) errs.push("V1, V2, V3 must be > 0");
      }

    }

  // dosing validity: program OR schedule OR repeat rule
  if (program.length === 0) {
    if (schedule.length === 0) {
      if (!(repeatCount > 0)) errs.push("# doses must be > 0 (repeat rule)");
      if (!(repeatDose  > 0)) errs.push("Dose must be > 0 (repeat rule)");
      if (!(repeatTau   > 0)) errs.push("τ must be > 0 (repeat rule)");
    } else {
      schedule.forEach((d, i) => {
        if (d.time == null || Number.isNaN(Number(d.time))) errs.push(`Dose row ${i+1}: time is invalid`);
        if (!(Number(d.dose) > 0)) errs.push(`Dose row ${i+1}: dose must be > 0`);
        if (rxRoute === "iv_infusion" && !(Number(d.Tinf ?? Tinf) > 0)) {
          errs.push(`Dose row ${i+1}: Tinf must be > 0`);
        }
      });
    }
  }

    return errs;
  }, [
    selectedModel, rxRoute, Vd, kel, ka, Tinf, tEnd, dt, paramMode,
    // 2c deps already present:
    alpha, beta, k10, k12, k21, V1,
    // 3c macro deps:
    A3, alpha3, B3, beta3, C3, gamma3,
    // 3c micro deps:
    k103, k123, k213, k133, k313, V13, V23, V33,
    // dosing/grid:
    schedule, repeatCount, repeatDose, repeatTau
  ]);

  // Call backend /simulate_pk
  const runSim = async () => {
    const errs = simErrors;
    if (errs.length) return alert("Fix these first:\n- " + errs.join("\n- "));

    const modelKey =
      selectedModel === "one" ? "1c" :
      (selectedModel === "two" ? "2c" : "3c");

    const params = {};

    if (modelKey === "1c") {
      params.Vd  = Number(Vd);
      params.kel = Number(kel);
    } else if (modelKey === "2c") {
      if (paramMode === "macro") {
        params.A     = Number(A);
        params.alpha = Number(alpha);
        params.B     = Number(B);
        params.beta  = Number(beta);
      } else {
        params.k10 = Number(k10);
        params.k12 = Number(k12);
        params.k21 = Number(k21);
        params.V1  = Number(V1);
      }
    } else {
      if (paramMode === "macro") {
        params.A = Number(A3); params.alpha = Number(alpha3);
        params.B = Number(B3); params.beta  = Number(beta3);
        params.C = Number(C3); params.gamma = Number(gamma3);
      } else {
        params.k10 = Number(k103);
        params.k12 = Number(k123);
        params.k21 = Number(k213);
        params.k13 = Number(k133);
        params.k31 = Number(k313);
        params.V1  = Number(V13);
        params.V2  = Number(V23);  
        params.V3  = Number(V33);
      }
    }
    // keep these in params so program steps can borrow defaults
    params.F    = Number(F);
    params.ka   = Number(ka);
    params.Tinf = Number(Tinf);

    // choose one dosing specification (backend priority: program > dosing > repeat)
    const body = {
      model: modelKey,
      route: rxRoute,
      params,
      t_end: Number(tEnd),
      dt: Number(dt),
      ...(program.length > 0
        ? { program }
        : schedule.length > 0
          ? { dosing: schedule }
          : {
              repeat: {
                start: Number(repeatStart),
                tau: Number(repeatTau),
                count: Number(repeatCount),
                dose: Number(useMgPerKg ? repeatDose * weightKg : repeatDose),
                Tinf: Number(Tinf),
              }
            })
    };

    try {
      const res = await axios.post("/simulate_pk", body);
      setSim(res.data);
    } catch (err) {
      alert("Sim error: " + (err.response?.data?.detail || err.message));
    }
  };

  // Call backend /what_if (supports mg/kg, weight, simple optimizer)
  const runWhatIf = async () => {
    const modelKey =
      selectedModel === "one" ? "1c" :
      (selectedModel === "two" ? "2c" : "3c");

    const params = {};
    if (modelKey === "1c") {
      params.Vd  = Number(Vd);
      params.kel = Number(kel);
    } 
    
    else if (modelKey === "2c") {
      if (paramMode === "macro") {
        params.A     = Number(A);
        params.alpha = Number(alpha);
        params.B     = Number(B);
        params.beta  = Number(beta);
      } else {
        params.k10 = Number(k10);
        params.k12 = Number(k12);
        params.k21 = Number(k21);
        params.V1  = Number(V1);
      }
    } else {
      if (paramMode === "macro") {
        params.A = Number(A3); params.alpha = Number(alpha3);
        params.B = Number(B3); params.beta  = Number(beta3);
        params.C = Number(C3); params.gamma = Number(gamma3);
      } else {
        params.k10 = Number(k103);
        params.k12 = Number(k123);
        params.k21 = Number(k213);
        params.k13 = Number(k133);
        params.k31 = Number(k313);
        params.V1  = Number(V13);
        params.V2  = Number(V23);
        params.V3  = Number(V33);
      }
    }
    params.F    = Number(F);
    params.ka   = Number(ka);
    params.Tinf = Number(Tinf);

    const payload = {
      model: modelKey,
      route: rxRoute,
      params,
      weight_kg: Number(weightKg),
      dose_spec: useMgPerKg
        ? { dose_mg_per_kg: Number(repeatDose) }
        : { dose_mg: Number(repeatDose) },
      tau: Number(repeatTau),
      count: Number(repeatCount),
      start: Number(repeatStart),
      Tinf: Number(Tinf),
      t_end: Number(tEnd),
      dt: Number(dt),
      ...(optTargetCmax && modelKey === "1c" && rxRoute === "iv_bolus"
        ? { optimize: { target_Cmax_ss: Number(optTargetCmax) || 0 } }
        : {})
    };
    
    try {
      const res = await axios.post("/what_if", payload);
      setSim(res.data);
    } catch (err) {
      alert("What-If error: " + (err.response?.data?.detail || err.message));
    }
  };

  // Simple SVG plot
  const Plot = ({ time, conc, dosing, width=700, height=300, margin=40 }) => {
    if (!time || !conc || time.length !== conc.length || time.length === 0) return null;
    const tmin = Math.min(...time), tmax = Math.max(...time);
    const x = t => margin + (t - tmin) * (width - 2*margin) / (tmax - tmin || 1);

    // linear vs log-y scaling
    let y, labelY;
    if (logY) {
      const positives = conc.filter(v => v > 0);
      const eps = positives.length ? Math.min(...positives) * 0.1 : 1e-6;
      const logs = conc.map(v => Math.log10(Math.max(v, eps)));
      const cminL = Math.min(...logs), cmaxL = Math.max(...logs);
      y = c => {
        const cv = Math.log10(Math.max(c, eps));
        return height - margin - (cv - cminL) * (height - 2*margin) / (cmaxL - cminL || 1);
      };
      labelY = "log10 Conc";
    } else {
      const cmin = 0, cmax = Math.max(...conc) * 1.1 || 1;
      y = c => height - margin - (c - cmin) * (height - 2*margin) / (cmax - cmin || 1);
      labelY = "Conc";
    }
    const pts = time.map((t,i) => `${x(t)},${y(conc[i])}`).join(" ");

    return (
      <svg width={width} height={height} className="pk-chart">
        {/* axes */}
        <line x1={margin} y1={height-margin} x2={width-margin} y2={height-margin} stroke="#888"/>
        <line x1={margin} y1={margin} x2={margin} y2={height-margin} stroke="#888"/>

        {/* infusion spans (shaded) */}
        {rxRoute === "iv_infusion" && Array.isArray(dosing) && dosing.map((d, i) => {
          const tinf = Number(d.Tinf ?? Tinf);
          if (!(tinf > 0)) return null;
          const x1 = x(d.time);
          const x2 = x(d.time + tinf);
          const w  = Math.abs(x2 - x1);
          const xL = Math.min(x1, x2);
          return (
            <rect key={`span-${i}`} x={xL} y={margin} width={w} height={height - 2*margin}
                  fill="#999" opacity="0.15" />
          );
        })}

        {/* curve */}
        <polyline fill="none" stroke="#007bff" strokeWidth="2" points={pts}/>
        {/* dose ticks */}
        {Array.isArray(dosing) && dosing.map((d, i) => (
          <line key={i} x1={x(d.time)} x2={x(d.time)} y1={height-margin} y2={margin} stroke="#bbb" strokeDasharray="3 4"/>
        ))}
        {/* labels */}
        <text x={width/2} y={height-8} textAnchor="middle" fontSize="12">Time (h)</text>
        <text x={16} y={margin-10} fontSize="12">{labelY}</text>

        {/* legend text */}
        <text x={width - margin} y={margin - 12} textAnchor="end" fontSize="12">
          {rxRoute === "iv_bolus" && "Route: IV bolus"}
          {rxRoute === "iv_infusion" && "Route: IV infusion"}
          {rxRoute === "oral" && `Route: Oral (F=${Number(F).toFixed(2)}, ka=${Number(ka).toFixed(2)} 1/h)`}
          {rxRoute === "sc" && `Route: SC (F=${Number(F).toFixed(2)}, ka=${Number(ka).toFixed(2)} 1/h)`}
        </text>

        {/* infusion legend swatch */}
        {rxRoute === "iv_infusion" && (
          <g transform={`translate(${width - margin - 140}, ${margin - 22})`}>
            <rect x="0" y="0" width="18" height="8" fill="#999" opacity="0.15" stroke="#999"/>
            <text x="24" y="8" fontSize="12">Infusion window</text>
          </g>
        )}
      </svg>
    );
  };

  return (
    <div className="container">
      <h1>PB–PK Simulator</h1>
      <div className="input-row">
        <label>
          Preset:&nbsp;
          <select value={preset} onChange={e => setPreset(e.target.value)}>
            {PRESET_NAMES.map(n => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        <span style={{marginLeft:12, fontSize:'.9rem', color:'#555'}}>
          EV defaults preload t½≈0.7–3.5 h (kel≈0.2–1.0 h⁻¹) and faster distribution.
        </span>
      </div>

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
          <button onClick={() => setSelectedModel("three")}>
            Three-Compartment Model
          </button>
        </div>
      )}

      {selectedModel && (
        <>
      <h2>
        {selectedModel === "one" ? "One-Compartment Model" :
         selectedModel === "two" ? "Two-Compartment Model" :
                                   "Three-Compartment Model"}
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

          {selectedModel === "three" && (
            <>
              <div className="input-row">
                <label> Parametrization:&nbsp;
                  <select value={paramMode} onChange={e => setParamMode(e.target.value)}>
                    <option value="macro">Macro (A, α, B, β, C, γ)</option>
                    <option value="micro">Micro (k10, k12, k21, k13, k31, V1)</option>
                  </select>
                </label>
                &nbsp;&nbsp;
                {paramMode === "macro" && (
                  <label> Use fitted A, α, B, β, C, γ:&nbsp;
                    <input type="checkbox" checked={useFitThreeMacros}
                          onChange={e=>setUseFitThreeMacros(e.target.checked)} />
                  </label>
                )}
              </div>
              {paramMode === "macro" ? (
                <div className="input-row">
                  <label>A (1/L):&nbsp;<input type="number" value={A3} onChange={e=>setA3(parseFloat(e.target.value))} style={{width:90}}/></label>&nbsp;
                  <label>α (1/h):&nbsp;<input type="number" value={alpha3} onChange={e=>setAlpha3(parseFloat(e.target.value))} style={{width:90}}/></label>&nbsp;
                  <label>B (1/L):&nbsp;<input type="number" value={B3} onChange={e=>setB3(parseFloat(e.target.value))} style={{width:90}}/></label>&nbsp;
                  <label>β (1/h):&nbsp;<input type="number" value={beta3} onChange={e=>setBeta3(parseFloat(e.target.value))} style={{width:90}}/></label>&nbsp;
                  <label>C (1/L):&nbsp;<input type="number" value={C3} onChange={e=>setC3(parseFloat(e.target.value))} style={{width:90}}/></label>&nbsp;
                  <label>γ (1/h):&nbsp;<input type="number" value={gamma3} onChange={e=>setGamma3(parseFloat(e.target.value))} style={{width:90}}/></label>
                </div>
              ) : (
                <>
                  <div className="input-row">
                    <label>k₁₀ (1/h):&nbsp;<input type="number" value={k103} onChange={e=>setK103(parseFloat(e.target.value))} style={{width:90}}/></label>&nbsp;
                    <label>k₁₂ (1/h):&nbsp;<input type="number" value={k123} onChange={e=>setK123(parseFloat(e.target.value))} style={{width:90}}/></label>&nbsp;
                    <label>k₂₁ (1/h):&nbsp;<input type="number" value={k213} onChange={e=>setK213(parseFloat(e.target.value))} style={{width:90}}/></label>
                  </div>
                  <div className="input-row">
                    <label>k₁₃ (1/h):&nbsp;<input type="number" value={k133} onChange={e=>setK133(parseFloat(e.target.value))} style={{width:90}}/></label>&nbsp;
                    <label>k₃₁ (1/h):&nbsp;<input type="number" value={k313} onChange={e=>setK313(parseFloat(e.target.value))} style={{width:90}}/></label>&nbsp;
                    <label>V₁ (L):&nbsp;<input type="number" value={V13} onChange={e=>setV13(parseFloat(e.target.value))} style={{width:90}}/></label>
                  </div>
                  <div className="input-row">
                    <label>V₂ (L):&nbsp;<input type="number" value={V23} onChange={e=>setV23(parseFloat(e.target.value))} style={{width:90}}/></label>&nbsp;
                    <label>V₃ (L):&nbsp;<input type="number" value={V33} onChange={e=>setV33(parseFloat(e.target.value))} style={{width:90}}/></label>
                  </div>
                </>
              )}
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
                    : selectedModel === "two"
                    ? "Fit Two-Compartment"
                    : "Fit Three-Compartment"}
                </button>
                <button onClick={downloadReport}>
                  Download PDF Report
                </button>
              </div>
            </div>
          )}

          <div className="preview-section">
            <h3>
              {selectedModel === "one" ? "Route Explorer (One-Compartment)"
              : selectedModel === "two" ? "Route Explorer (Two-Compartment)"
              : "Route Explorer (Three-Compartment)"}
            </h3>

            {/* Program Builder */}
            <div className="input-row">
              <strong>Program builder</strong>&nbsp;
              <button onClick={() => setProgram([...program, {type:"bolus", time:0, dose:100}])}>+ Bolus</button>
              <button onClick={() => setProgram([...program, {type:"infusion", start:0, dose:1000, Tinf:1}])}>+ Infusion</button>
              <button onClick={() => setProgram([...program, {type:"repeat", pattern:"bolus", start:0, tau:8, count:6, dose:100}])}>+ Repeat (bolus)</button>
            </div>
            {program.length > 0 && (
              <table className="preview-table">
                <thead>
                  <tr><th>Type</th><th>Fields</th><th></th></tr>
                </thead>
                <tbody>
                  {program.map((step, i) => (
                    <tr key={i}>
                      <td>{step.type}</td>
                      <td>
                        <input
                          style={{width: '95%'}}
                          value={JSON.stringify(step)}
                          onChange={e=>{
                            try { 
                              const parsed = JSON.parse(e.target.value);
                              const copy = program.slice(); copy[i] = parsed; setProgram(copy);
                            } catch{}
                          }}
                        />
                      </td>
                      <td><button onClick={()=>{ const copy=program.slice(); copy.splice(i,1); setProgram(copy);}}>Remove</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

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
              {selectedModel === "one" ? (
                <label>
                  Use fitted Vd, kel:&nbsp;
                  <input
                    type="checkbox"
                    checked={useFitParams}
                    onChange={e => setUseFitParams(e.target.checked)}
                  />
                </label>
              ) : selectedModel === "two" ? (
                <>
                  <label> Parametrization:&nbsp;
                    <select value={paramMode} onChange={e => setParamMode(e.target.value)}>
                      <option value="macro">Macro (A, α, B, β)</option>
                      <option value="micro">Micro (k10, k12, k21, V1)</option>
                    </select>
                  </label>
                  &nbsp;&nbsp;
                  {paramMode === "macro" && (
                    <label> Use fitted A, α, B, β:&nbsp;
                      <input
                        type="checkbox"
                        checked={useFitTwoMacros}
                        onChange={e => setUseFitTwoMacros(e.target.checked)}
                      />
                    </label>
                  )}
                </>
              ) : null}
            </div>

            {selectedModel === "one" ? (
              <div className="input-row">
                <label title="Apparent volume of distribution (L)">Vd (L):&nbsp;
                  <input type="number" min="0.001" max="2000" step="0.001"
                    value={Vd} onChange={e=>setVd(parseFloat(e.target.value))} style={{width:110}}/>
                </label>
                &nbsp;
                <label title="Elimination rate constant (1/h)">kel (1/h):&nbsp;
                  <input type="number" min="0.02" max="5.0" step="0.01"
                    value={kel} onChange={e=>setKel(parseFloat(e.target.value))} style={{width:110}}/>
                </label>
                {rxRoute === "iv_infusion" && (
                  <>
                    &nbsp;
                    <label title="Infusion duration per dose (hours)">Tinf (h):&nbsp;
                      <input type="number" min="0.01" step="0.01"
                        value={Tinf} onChange={e=>setTinf(parseFloat(e.target.value))} style={{width:90}}/>
                    </label>
                  </>
                )}
                {(rxRoute === "oral" || rxRoute === "sc") && (
                  <>
                    &nbsp;
                    <label title="Bioavailability fraction (unitless)">F:&nbsp;
                      <input type="number" min="0" max="1" step="0.01"
                        value={F} onChange={e=>setF(parseFloat(e.target.value))} style={{width:90}}/>
                    </label>
                    &nbsp;
                    <label title="Absorption rate constant (1/h)">ka (1/h):&nbsp;
                      <input type="number" min="0.05" max="10" step="0.01"
                        value={ka} onChange={e=>setKa(parseFloat(e.target.value))} style={{width:90}}/>
                    </label>
                  </>
                )}
              </div>
            ) : selectedModel === "two" ? (
              <>
                {paramMode === "macro" ? (
                  <div className="input-row">
                    <label title="Macro coefficient A (≈ 1/L for unit dose)">A (1/L):&nbsp;
                      <input type="number" value={A} onChange={e=>setA(parseFloat(e.target.value))} style={{width:90}}/>
                    </label>
                    &nbsp;
                    <label title="Macro rate α (1/h)">α (1/h):&nbsp;
                      <input type="number" min="0.05" max="5" step="0.01"
                        value={alpha} onChange={e=>setAlpha(parseFloat(e.target.value))} style={{width:90}}/>
                    </label>
                    &nbsp;
                     <label title="Macro coefficient B (≈ 1/L for unit dose)">B (1/L):&nbsp;
                      <input type="number" value={B} onChange={e=>setB(parseFloat(e.target.value))} style={{width:90}}/>
                    </label>
                    &nbsp;
                    <label title="Macro rate β (1/h)">β (1/h):&nbsp;
                      <input type="number" min="0.01" max="2" step="0.01"
                        value={beta} onChange={e=>setBeta(parseFloat(e.target.value))} style={{width:90}}/>
                    </label>
                  </div>
                ) : (
                  <div className="input-row">
                    <label title="Elimination from central (1/h)">k₁₀ (1/h):&nbsp;
                      <input type="number" min="0.02" max="5" step="0.01"
                        value={k10} onChange={e=>setK10(parseFloat(e.target.value))} style={{ width: 90 }}/>
                    </label>
                    &nbsp;
                    <label title="Distribution central→peripheral (1/h)">k₁₂ (1/h):&nbsp;
                      <input type="number" min="0.02" max="5" step="0.01"
                        value={k12} onChange={e=>setK12(parseFloat(e.target.value))} style={{ width: 90 }}/>
                    </label>
                    &nbsp;
                    <label title="Distribution peripheral→central (1/h)">k₂₁ (1/h):&nbsp;
                      <input type="number" min="0.02" max="5" step="0.01"
                        value={k21} onChange={e=>setK21(parseFloat(e.target.value))} style={{ width: 90 }}/>
                    </label>
                    &nbsp;
                     <label title="Central compartment volume (L)">V₁ (L):&nbsp;
                      <input type="number" min="0.001" max="2000" step="0.001"
                        value={V1} onChange={e=>setV1(parseFloat(e.target.value))} style={{ width: 90 }}/>
                    </label>
                  </div>
                )}
                <div className="input-row">
                  {rxRoute === "iv_infusion" && (
                    <>
                      <label title="Infusion duration per dose (hours)">Tinf (h):&nbsp;
                        <input type="number" value={Tinf} onChange={e=>setTinf(parseFloat(e.target.value))} style={{width:90}}/>
                      </label>
                      &nbsp;
                    </>
                  )}
                  {(rxRoute === "oral" || rxRoute === "sc") && (
                    <>
                      <label title="Bioavailability fraction (unitless)">F:&nbsp;
                        <input type="number" min="0" max="1" step="0.01"
                          value={F} onChange={e=>setF(parseFloat(e.target.value))} style={{width:90}}/>
                      </label>
                      &nbsp;
                      <label title="Absorption rate constant (1/h)">ka (1/h):&nbsp;
                        <input type="number" min="0.05" max="10" step="0.01"
                          value={ka} onChange={e=>setKa(parseFloat(e.target.value))} style={{width:90}}/>
                      </label>
                    </>
                  )}
                </div>
              </>
            ): null}

            {selectedModel === "three" && (
              <div className="input-row">
                {rxRoute === "iv_infusion" && (
                  <>
                    <label title="Infusion duration per dose (hours)">Tinf (h):&nbsp;
                      <input
                        type="number"
                        value={Tinf}
                        onChange={e => setTinf(parseFloat(e.target.value))}
                        style={{ width: 90 }}
                      />
                    </label>
                    &nbsp;
                  </>
                )}
                {(rxRoute === "oral" || rxRoute === "sc") && (
                  <>
                    <label title="Bioavailability fraction (unitless)">F:&nbsp;
                      <input
                        type="number" min="0" max="1" step="0.01"
                        value={F}
                        onChange={e => setF(parseFloat(e.target.value))}
                        style={{ width: 90 }}
                      />
                    </label>
                    &nbsp;
                    <label title="Absorption rate constant (1/h)">ka (1/h):&nbsp;
                      <input
                        type="number" min="0.05" max="10" step="0.01"
                        value={ka}
                        onChange={e => setKa(parseFloat(e.target.value))}
                        style={{ width: 90 }}
                      />
                    </label>
                  </>
                )}
              </div>
            )}

            <fieldset style={{border:'1px solid #ddd', padding:12, borderRadius:8, marginTop:12}}>
              <legend>What-If Dosing</legend>
              <label style={{display:'block', margin:'6px 0'}}>
                Dose units:&nbsp;
                <select
                  value={useMgPerKg ? "mg/kg" : "mg"}
                  onChange={e => setUseMgPerKg(e.target.value === "mg/kg")}
                >
                  <option value="mg">mg</option>
                  <option value="mg/kg">mg/kg</option>
                </select>
              </label>

              <label style={{display:'block', margin:'6px 0'}}>
                {useMgPerKg ? "Dose (mg/kg)" : "Dose (mg)"}: {repeatDose}
                <input
                  type="range" min="1" max="2000" step="1"
                  value={repeatDose}
                  onChange={e => setRepeatDose(Number(e.target.value))}
                />
              </label>

              <label style={{display:'block', margin:'6px 0'}}>
                τ (interval, h): {repeatTau}
                <input
                  type="range" min="1" max="48" step="0.5"
                  value={repeatTau}
                  onChange={e => setRepeatTau(Number(e.target.value))}
                />
              </label>

              {rxRoute === "iv_infusion" && (
                <label style={{display:'block', margin:'6px 0'}}>
                  Infusion time Tinf (h): {Tinf}
                  <input
                    type="range" min="0.1" max="24" step="0.1"
                    value={Tinf}
                    onChange={e => setTinf(Number(e.target.value))}
                  />
                </label>
              )}

              <label style={{display:'block', margin:'6px 0'}}>
                Body weight (kg): {weightKg}
                <input
                  type="range" min="1" max="120" step="1"
                  value={weightKg}
                  onChange={e => setWeightKg(Number(e.target.value))}
                />
              </label>

              <label style={{display:'block', margin:'6px 0'}}>
                Target Cmax_ss (1c IV bolus):&nbsp;
                <input
                  type="number" min="0" step="0.01" placeholder="leave blank to disable"
                  value={optTargetCmax}
                  onChange={e => setOptTargetCmax(e.target.value)}
                  style={{ width: 160 }}
                />
              </label>
              <div style={{marginTop:8}}>
                <button type="button" onClick={makeRepeatSchedule}>Apply to Schedule</button>
                <button type="button" style={{marginLeft:8}} onClick={runSim}>Simulate</button>
                <button type="button" style={{marginLeft:8}} onClick={runWhatIf}>Simulate (What-If)</button>
              </div>
            </fieldset>

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
                <label title="Simulation end time (hours)">t_end (h):&nbsp;
                <input type="number" min="1" max="168" step="1"
                  value={tEnd} onChange={e=>setTEnd(parseFloat(e.target.value))} style={{width:90}}/>
              </label>
              &nbsp;
              <label>dt (h):&nbsp;
                <input type="number" min="0.001" step="0.001"
                  value={dt} onChange={e=>setDt(parseFloat(e.target.value))} style={{width:90}}/>
              </label>
              &nbsp;

              <label>
                <input type="checkbox" checked={logY} onChange={e=>setLogY(e.target.checked)} />
                &nbsp;Semilog Y
              </label>
              &nbsp;
              <button onClick={runSim} disabled={simErrors.length > 0}>Simulate</button>
            </div>
            {simErrors.length > 0 && (
              <div className="error-list">
                {simErrors.slice(0,5).map((e,i) => <div key={i}>• {e}</div>)}
                {simErrors.length > 5 && <div>• ...and {simErrors.length - 5} more</div>}
              </div>
            )}

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
                <Plot time={sim.time} conc={sim.conc} dosing={sim.dosing} />
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
                  selectedModel === "two" ? (
                    <>
                      <li>A = {r.fit.A.toFixed(3)}</li>
                      <li>α = {r.fit.alpha.toFixed(3)}</li>
                      <li>B = {r.fit.B.toFixed(3)}</li>
                      <li>β = {r.fit.beta.toFixed(3)}</li>
                    </>
                  ) : (
                    <>
                      <li>A = {r.fit.A.toFixed(3)}</li>
                      <li>α = {r.fit.alpha.toFixed(3)}</li>
                      <li>B = {r.fit.B.toFixed(3)}</li>
                      <li>β = {r.fit.beta.toFixed(3)}</li>
                      <li>C = {r.fit.C.toFixed(3)}</li>
                      <li>γ = {r.fit.gamma.toFixed(3)}</li>
                    </>
                  )
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
