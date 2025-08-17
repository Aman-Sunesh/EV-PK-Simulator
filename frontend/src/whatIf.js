import axios from "axios";

const API = axios.create({
  baseURL: process.env.REACT_APP_API_BASE || "http://localhost:8000",
});

export async function runWhatIf(payload) {
  const { data } = await API.post("/what_if", payload);
  return data;
}

export async function runWhatIfBatch(scenarios) {
  const { data } = await API.post("/what_if_batch", { scenarios });
  return data; // { results: [{label, ok, result|error}, ...] }
}