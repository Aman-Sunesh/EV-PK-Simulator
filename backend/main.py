from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd

app = FastAPI()

# allow your React dev server to talk to this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "OK"}

@app.post("/upload")
async def upload_csv(file: UploadFile = File(...)):
    # read into DataFrame
    try:
        if file.filename.lower().endswith((".xls", ".xlsx")):
            df = pd.read_excel(file.file)
        else:
            df = pd.read_csv(file.file)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse file: {e}")

    # normalize column names
    cols = {c.lower(): c for c in df.columns}
    df.rename(columns=cols, inplace=True)

    required = {"time", "concentration"}
    missing = required - set(df.columns)
    warnings = [f"Missing required column: {m}" for m in missing] if missing else []

    preview = df.head().to_dict(orient="records")

    return {"preview": preview, "warnings": warnings}

@app.post("/fit/one_compartment")
async def fit_one(data: dict):
    """
    Expects JSON: {"time": [...], "concentration": [...]}
    """
    time = data.get("time", [])
    conc = data.get("concentration", [])
    params = stub_one_compartment(time, conc)
    return params