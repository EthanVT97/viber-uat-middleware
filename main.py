from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import requests
import time
from log_storage import add_log, log_store
from config import Config
import json # Used for Viber signature verification placeholder

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# ===== MODELS =====
class ViberWebhook(BaseModel):
    event: str
    sender: dict  # { "id": "user123", "name": "John" }
    message: dict = None  # { "text": "Hello", "type": "text" }, can be None for other events
    timestamp: int
    user: dict = None # present for subscribed event
    subscribed: str = None # present for subscribed event

class CustomerCreate(BaseModel):
    name: str
    phone: str
    region: str = "Viber User"
    viber_id: str = None

class PaymentCreate(BaseModel):
    user_id: str
    amount: int
    method: str
    reference_id: str

# ===== VIBER WEBHOOK =====
@app.post("/viber-webhook")
async def viber_webhook(
    data: ViberWebhook,
    viber_signature: str = Header(..., alias="X-Viber-Content-Signature")
):
    """Handle Viber Bot webhooks"""
    # Note: `data.dict()` will be called implicitly by Pydantic's BaseModel
    # conversion, but for signature verification, the raw request body is often
    # needed. For this placeholder, we'll use `data.json()` or `data.dict()`

    # Verify signature (placeholder)
    # In a real scenario, you'd calculate the HMAC-SHA256 hash of the raw
    # request body using your bot's app key and compare it with the signature.
    # For now, we use a simple placeholder.
    # if not verify_viber_signature(viber_signature, data.json()): # This would require raw body
    #     raise HTTPException(status_code=403, detail="Invalid signature")

    # Let's keep the simple placeholder as requested in the original comment
    # For robust verification, you'd need the raw request body before Pydantic parsing.
    # Since we don't have access to the raw body here directly without custom middleware,
    # we'll assume the current placeholder for demo purposes.
    if not verify_viber_signature(viber_signature, data.dict()): # This is not how Viber signature works, see note below
        raise HTTPException(status_code=403, detail="Invalid signature")


    # Log and process
    add_log({
        "endpoint": "/viber-webhook",
        "status": "✅",
        "payload": data.dict()
    })

    if data.event == "message":
        return await process_viber_message(data)
    elif data.event == "subscribed":
        # Handle new subscriptions, e.g., send a welcome message
        add_log({
            "endpoint": "/viber-webhook",
            "status": "✅",
            "message": f"User {data.user.get('name', 'Unknown')} ({data.user.get('id')}) subscribed.",
            "payload": data.dict()
        })
        # You could send a welcome message here using the Viber API
        return {"status": "subscribed_event_handled"}
    elif data.event == "conversation_started":
        # Handle conversation started events (e.g., initial greeting)
        add_log({
            "endpoint": "/viber-webhook",
            "status": "✅",
            "message": f"Conversation started with {data.user.get('name', 'Unknown')} ({data.user.get('id')}).",
            "payload": data.dict()
        })
        # You could send a greeting message here using the Viber API
        return {"status": "conversation_started_event_handled"}
    # Add more event types as needed (delivered, seen, failed, unsubscribed, etc.)

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

@app.post("/uat/payments")
async def record_payment(data: PaymentCreate, authorization: str = Header(...)):
    """UAT Payment Recording API"""
    if authorization != f"Bearer {Config.BILLING_API_KEY}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    add_log({
        "endpoint": "/uat/payments",
        "status": "✅",
        "payload": data.dict()
    })
    return {"status": "success", "message": "Payment recorded successfully", "payment_id": data.reference_id}

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
            parts = text.split(maxsplit=3) # "create", "customer", "Name", "Phone"
            if len(parts) < 4:
                raise ValueError("Insufficient arguments. Expected: create customer <name> <phone>")
            name = parts[2]
            phone = parts[3]
            response = await create_customer_via_api(name, phone, user_id)
            return {"status": "success", "message": f"Customer creation initiated: {response.get('message', str(response))}"}
        except Exception as e:
            add_log({
                "endpoint": "/viber-webhook",
                "status": "❌",
                "message": f"Error processing 'create customer': {str(e)}",
                "payload": data.dict()
            })
            return {"status": "error", "message": f"Invalid format or error: {str(e)}. Use 'create customer <name> <phone>'"}

    elif text.startswith("pay"):
        try:
            parts = text.split(maxsplit=2) # "pay", "amount"
            if len(parts) < 2:
                raise ValueError("Insufficient arguments. Expected: pay <amount>")
            amount = int(parts[1])
            response = await record_payment_via_api(user_id, amount)
            return {"status": "success", "message": f"Payment initiated: {response.get('message', str(response))}"}
        except ValueError:
            add_log({
                "endpoint": "/viber-webhook",
                "status": "❌",
                "message": f"Invalid amount for 'pay' command: {text}",
                "payload": data.dict()
            })
            return {"status": "error", "message": "Invalid amount. Use 'pay <amount>' where amount is a number."}
        except Exception as e:
            add_log({
                "endpoint": "/viber-webhook",
                "status": "❌",
                "message": f"Error processing 'pay' command: {str(e)}",
                "payload": data.dict()
            })
            return {"status": "error", "message": f"Error processing payment: {str(e)}"}
    else:
        # Default response for unhandled messages
        return {"status": "received", "message": "Thank you for your message!"}


async def create_customer_via_api(name: str, phone: str, viber_id: str):
    """Call UAT Customer API"""
    payload = CustomerCreate(name=name, phone=phone, viber_id=viber_id).dict()
    # Using Config.BASE_URL for the target API
    try:
        response = requests.post(
            f"{Config.BASE_URL}/uat/customers/create",
            json=payload,
            headers={"Authorization": f"Bearer {Config.CUSTOMER_API_KEY}"},
            timeout=5 # Add a timeout for external requests
        )
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        return response.json()
    except requests.exceptions.RequestException as e:
        add_log({
            "endpoint": "/create_customer_via_api",
            "status": "❌",
            "message": f"API call failed: {str(e)}",
            "payload": payload
        })
        raise HTTPException(status_code=500, detail=f"Failed to create customer: {e}")

async def record_payment_via_api(user_id: str, amount: int):
    """Call UAT Payment API"""
    payload = PaymentCreate(
        user_id=user_id,
        amount=amount,
        method="ViberPay",
        reference_id=f"VIBER-{int(time.time())}-{user_id[:5]}" # Add user_id prefix for better uniqueness
    ).dict()
    # Using Config.BASE_URL for the target API
    try:
        response = requests.post(
            f"{Config.BASE_URL}/uat/payments",
            json=payload,
            headers={"Authorization": f"Bearer {Config.BILLING_API_KEY}"},
            timeout=5 # Add a timeout for external requests
        )
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        return response.json()
    except requests.exceptions.RequestException as e:
        add_log({
            "endpoint": "/record_payment_via_api",
            "status": "❌",
            "message": f"API call failed: {str(e)}",
            "payload": payload
        })
        raise HTTPException(status_code=500, detail=f"Failed to record payment: {e}")


def verify_viber_signature(signature: str, payload_dict: dict) -> bool:
    """Verify Viber webhook signature (placeholder)"""
    # TODO: Implement actual signature verification
    # Actual Viber signature verification requires:
    # 1. Access to the raw request body as bytes.
    # 2. Your Viber Bot's App Key (secret).
    # 3. Calculate HMAC-SHA256 of the raw body using the app key.
    # 4. Compare the calculated hash (hex digest) with the X-Viber-Content-Signature header.

    # Example (concept, not executable without raw body):
    # import hmac
    # import hashlib
    # app_key = Config.VIBER_BOT_APP_KEY.encode('utf-8')
    # calculated_signature = hmac.new(app_key, raw_body, hashlib.sha256).hexdigest()
    # return calculated_signature == signature

    # For this exercise, we keep it simple as originally indicated.
    # In a real app, this `return True` would be a severe security flaw.
    return True

# ===== RUN LOCALLY =====
if __name__ == "__main__":
    import uvicorn
    # Make sure 'templates' directory exists and 'monitor.html' is inside it.
    # Make sure 'log_storage.py' and 'config.py' are in the same directory.
    uvicorn.run("main:app", host="0.0.0.0", port=10000, reload=True)
