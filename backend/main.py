from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from models import stub_one_compartment
import pandas as pd
from io import BytesIO


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
    # 1) read into DataFrame
    try:
        # read entire upload into memory
        contents = await file.read()
        buffer = BytesIO(contents)

        if file.filename.lower().endswith((".xls", ".xlsx")):
            df = pd.read_excel(buffer)
        else:
            # rewind buffer just in case
            buffer.seek(0)
            df = pd.read_csv(buffer)

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse file: {e}")

    # 2) normalize column names
    cols = {c.lower(): c for c in df.columns}
    df.rename(columns=cols, inplace=True)

    # 3) check for required columns
    required = {"time", "concentration"}
    missing = required - set(df.columns)
    warnings = [f"Missing required column: {m}" for m in missing] if missing else []

    # 4) build preview
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