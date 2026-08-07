"""ReturnGuard 复赛 Demo 后端（FastAPI）。"""
import os
import uuid

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pipeline import analyze_case, load_cases, save_case, build_insights

BASE = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
CASES_FILE = os.path.join(BASE, "cases.json")
INDEX = os.path.join(BASE, "static", "index.html")

app = FastAPI(title="ReturnGuard Demo")
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    with open(INDEX, "r", encoding="utf-8") as f:
        return f.read()


@app.post("/api/analyze")
async def analyze(
    returned_image: UploadFile = File(...),
    product_image: UploadFile = File(...),
    listing_text: str = Form(""),
    sku: str = Form("SKU-未知"),
    amount: float = Form(0.0),
    mode: str = Form("mock"),
):
    rid = uuid.uuid4().hex[:8]
    rp = os.path.join(UPLOAD_DIR, f"{rid}_ret_{returned_image.filename}")
    pp = os.path.join(UPLOAD_DIR, f"{rid}_prod_{product_image.filename}")
    with open(rp, "wb") as f:
        f.write(await returned_image.read())
    with open(pp, "wb") as f:
        f.write(await product_image.read())

    result = analyze_case(rp, pp, listing_text, sku, amount, mode)
    result["case_id"] = rid
    save_case(CASES_FILE, {
        **result, "sku": sku, "amount": amount,
        "returned_image": os.path.basename(rp),
        "product_image": os.path.basename(pp),
    })
    return JSONResponse(result)


@app.get("/api/insights")
def insights():
    return JSONResponse(build_insights(load_cases(CASES_FILE)))


@app.get("/api/cases")
def cases():
    return JSONResponse(load_cases(CASES_FILE))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
