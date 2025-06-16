import { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";
import axios from "axios";

export default function Upload() {
  const [preview, setPreview] = useState([]);
  const [warnings, setWarnings] = useState([]);
  const [fitParams, setFitParams] = useState(null);

  const onDrop = useCallback(async (files) => {
    // Reset previous fit results
    setFitParams(null);

    const data = new FormData();
    data.append("file", files[0]);

    try {
      const res = await axios.post("http://localhost:8000/upload", data);
      setPreview(res.data.preview);
      setWarnings(res.data.warnings);
    } catch (err) {
      console.error(err);
      alert("Upload failed: " + (err.response?.data?.detail || err.message));
    }
  }, []);

  const { getRootProps, getInputProps } = useDropzone({ onDrop });

  return (
    <div style={{ padding: 20 }}>
      <div
        {...getRootProps()}
        style={{
          border: "2px dashed #aaa",
          padding: 40,
          textAlign: "center",
          cursor: "pointer",
        }}
      >
        <input {...getInputProps()} />
        <p>Drag & drop a CSV or Excel file here, or click to select</p>
      </div>

      {!!warnings.length && (
        <div style={{ color: "orange", marginTop: 10 }}>
          {warnings.map((w, i) => (
            <div key={i}>{w}</div>
          ))}
        </div>
      )}

      {preview.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <h3>Data Preview</h3>
          <pre style={{ background: "#f6f8fa", padding: 10 }}>
            {JSON.stringify(preview, null, 2)}
          </pre>

          <button
            onClick={async () => {
              if (!preview.length) {
                return alert("Upload data first");
              }
              // extract arrays
              const time = preview.map((r) => r.time);
              const concentration = preview.map((r) => r.concentration);
              try {
                const res = await axios.post(
                  "http://localhost:8000/fit/one_compartment",
                  { time, concentration }
                );
                setFitParams(res.data);
              } catch (err) {
                console.error(err);
                alert("Fit error: " + (err.response?.data?.detail || err.message));
              }
            }}
            style={{ marginTop: 20, padding: "8px 16px" }}
          >
            Fit 1-Compartment
          </button>
        </div>
      )}

      {fitParams && (
        <div style={{ marginTop: 20 }}>
          <h3>Fit Results</h3>
          <ul>
            <li>Cl: {fitParams.Cl}</li>
            <li>Vd: {fitParams.Vd}</li>
            <li>t₁/₂: {fitParams.t_half}</li>
          </ul>
        </div>
      )}
    </div>
  );
}