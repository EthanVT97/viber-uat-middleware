from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import requests
import time
from log_storage import add_log, log_store
from config import Config

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# ===== MODELS =====
class ViberWebhook(BaseModel):
    event: str
    sender: dict  # { "id": "user123", "name": "John" }
    message: dict  # { "text": "Hello", "type": "text" }
    timestamp: int

class CustomerCreate(BaseModel):
    name: str
    phone: str
    region: str = "Viber User"
    viber_id: str = None

# ===== VIBER WEBHOOK =====
@app.post("/viber-webhook")
async def viber_webhook(
    data: ViberWebhook,
    viber_signature: str = Header(..., alias="X-Viber-Content-Signature")
):
    """Handle Viber Bot webhooks"""
    # Verify signature (simplified)
    if not verify_viber_signature(viber_signature, data):
        raise HTTPException(status_code=403, detail="Invalid signature")

    # Log and process
    add_log({
        "endpoint": "/viber-webhook",
        "status": "✅",
        "payload": data.dict()
    })

    if data.event == "message":
        return await process_viber_message(data)

    return {"status": "ignored"}

# ===== UAT APIS =====
@app.post("/uat/customers/create")
async def create_customer(data: CustomerCreate, authorization: str = Header(...)):
    """UAT Customer Creation API"""
    if authorization != f"Bearer {Config.CUSTOMER_API_KEY}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    add_log({
        "endpoint": "/uat/customers/create",
        "status": "✅",
        "payload": data.dict()
    })
    return {"status": "success", "message": "Customer created successfully"}

# ===== MONITOR UI =====
@app.get("/monitor", response_class=HTMLResponse)
async def monitor_ui(request: Request, token: str = ""):
    """Monitoring Dashboard"""
    if token != Config.MONITOR_TOKEN:
        raise HTTPException(status_code=403, detail="Access denied")
    return templates.TemplateResponse("monitor.html", {"request": request, "logs": log_store})

# ===== HELPER FUNCTIONS =====
async def process_viber_message(data: ViberWebhook):
    """Process Viber user messages"""
    user_id = data.sender["id"]
    text = data.message.get("text", "").lower()

    if text.startswith("create customer"):
        try:
            name, phone = text.split()[2:4]
            return await create_customer_via_api(name, phone, user_id)
        except Exception as e:
            return {"status": "error", "message": f"Invalid format: {str(e)}"}

    elif text.startswith("pay"):
        try:
            amount = int(text.split()[1])
            return await record_payment_via_api(user_id, amount)
        except Exception as e:
            return {"status": "error", "message": f"Invalid amount: {str(e)}"}

async def create_customer_via_api(name: str, phone: str, viber_id: str):
    """Call UAT Customer API"""
    payload = CustomerCreate(name=name, phone=phone, viber_id=viber_id).dict()
    response = requests.post(
        f"{Config.BASE_URL}/uat/customers/create",  # Fixed typo: 'customers' instead of 'customers'
        json=payload,
        headers={"Authorization": f"Bearer {Config.CUSTOMER_API_KEY}"}
    )
    return response.json()

async def record_payment_via_api(user_id: str, amount: int):
    """Call UAT Payment API"""
    payload = {
        "user_id": user_id,
        "amount": amount,
        "method": "ViberPay",
        "reference_id": f"VIBER-{int(time.time())}"
    }
    response = requests.post(
        f"{Config.BASE_URL}/uat/payments",
        json=payload,
        headers={"Authorization": f"Bearer {Config.BILLING_API_KEY}"}
    )
    return response.json()

def verify_viber_signature(signature: str, data: dict) -> bool:
    """Verify Viber webhook signature (placeholder)"""
    # TODO: Implement actual signature verification
    # For now, always return True for testing
    return True

# ===== RUN LOCALLY =====
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
