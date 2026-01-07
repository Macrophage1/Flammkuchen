# api_server.py
# Optional (empfohlen), wenn deine ESPs wirklich weiterhin:
#   GET /queue?status=...
#   POST /status  {"token":"firecake","queue_id":17,"status":"bereit_fuer_ofen"}
# sprechen sollen.
#
# Das ist ein kleiner FastAPI-Server, der auf dieselben GitHub-CSV-Dateien zugreift.
# Den hostest du z.B. bei Render/Fly/Hetzner. Streamlit bleibt nur die UI.

import os
import io
import csv
import json
import base64
from typing import Optional, List
from dataclasses import dataclass

import requests
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

DATA_DIR = os.getenv("DATA_DIR", "data_kasse")
USERS_CSV = f"{DATA_DIR}/users.csv"
PRODUCTS_CSV = f"{DATA_DIR}/products.csv"
ORDERS_CSV = f"{DATA_DIR}/orders.csv"
KITCHEN_QUEUE_CSV = f"{DATA_DIR}/kitchen_queue.csv"

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")

STATUS_TOKEN = os.getenv("STATUS_TOKEN", "firecake")

API = "https://api.github.com"

def headers():
    if not GITHUB_TOKEN:
        return {"Accept": "application/vnd.github+json"}
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
    }

def read_text(path: str) -> Optional[str]:
    url = f"{API}/repos/{GITHUB_REPO}/contents/{path}"
    r = requests.get(url, headers=headers(), params={"ref": GITHUB_BRANCH}, timeout=10)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    j = r.json()
    content = j.get("content", "")
    return base64.b64decode(content).decode("utf-8") if content else ""

def write_text(path: str, text: str, message: str):
    url = f"{API}/repos/{GITHUB_REPO}/contents/{path}"
    r0 = requests.get(url, headers=headers(), params={"ref": GITHUB_BRANCH}, timeout=10)
    sha = r0.json().get("sha") if r0.status_code == 200 else None

    payload = {
        "message": message,
        "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha

    r = requests.put(url, headers=headers(), json=payload, timeout=10)
    r.raise_for_status()

@dataclass
class KitchenItem:
    queue_id: int
    order_id: int
    product_name: str
    quantity: int
    special: str
    status: str
    timestamp: str

def load_kitchen_queue() -> List[KitchenItem]:
    raw = read_text(KITCHEN_QUEUE_CSV) or ""
    f = io.StringIO(raw)
    reader = csv.DictReader(f, delimiter=";")
    items: List[KitchenItem] = []
    for row in reader:
        if not row.get("queue_id"):
            continue
        items.append(
            KitchenItem(
                queue_id=int(row["queue_id"]),
                order_id=int(row["order_id"]),
                product_name=row.get("product_name",""),
                quantity=int(row.get("quantity","0") or 0),
                special=row.get("special",""),
                status=row.get("status","zu_belegen"),
                timestamp=row.get("timestamp",""),
            )
        )
    return items

def save_kitchen_queue(items: List[KitchenItem]):
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=["queue_id","order_id","product_name","quantity","special","status","timestamp"], delimiter=";")
    w.writeheader()
    for it in items:
        w.writerow({
            "queue_id": it.queue_id,
            "order_id": it.order_id,
            "product_name": it.product_name,
            "quantity": it.quantity,
            "special": it.special,
            "status": it.status,
            "timestamp": it.timestamp,
        })
    write_text(KITCHEN_QUEUE_CSV, out.getvalue(), "Update kitchen_queue.csv via API")

class StatusPayload(BaseModel):
    token: str
    queue_id: int
    status: str

app = FastAPI(title="Firecake Status API")

@app.get("/queue")
def get_queue(status: str = Query(..., pattern="^(zu_belegen|bereit_fuer_ofen|fertig)$")):
    items = load_kitchen_queue()
    payload_items = []
    for it in items:
        if it.status != status:
            continue
        payload_items.append({
            "queue_id": it.queue_id,
            "order_id": it.order_id,
            "name": it.product_name,
            "qty": it.quantity,
            "special": it.special or "",
            "timestamp": it.timestamp or "",
            "status": it.status,
        })
    return {"ok": True, "items": payload_items}

@app.post("/status")
def post_status(p: StatusPayload):
    if p.token != STATUS_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")
    if p.status not in ("zu_belegen","bereit_fuer_ofen","fertig"):
        raise HTTPException(status_code=400, detail="invalid_status")

    items = load_kitchen_queue()
    ok = False
    for it in items:
        if it.queue_id == p.queue_id:
            it.status = p.status
            ok = True
            break
    if ok:
        save_kitchen_queue(items)
    return {"ok": ok}
