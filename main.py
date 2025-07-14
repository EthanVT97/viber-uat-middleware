from fastapi import FastAPI, Request, Header, HTTPException, status
from pydantic import BaseModel
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime
import uvicorn
import os

from log_storage import add_log, log_store

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Load API keys from environment variables with fallback for local development
API_KEYS = {
    "CUSTOMER_API_KEY": os.getenv("CUSTOMER_API_KEY", "sandbox_customer_123"),
    "BILLING_API_KEY": os.getenv("BILLING_API_KEY", "sandbox_billing_456"),
    "CHATLOG_API_KEY": os.getenv("CHATLOG_API_KEY", "sandbox_chatlog_789")
}

class CustomerCreate(BaseModel):
    name: str
    phone: str
    region: str

class Payment(BaseModel):
    user_id: str
    amount: int
    method: str
    reference_id: str

class ChatLog(BaseModel):
    viber_id: str
    message: str
    timestamp: str
    type: str

def check_auth(token: str, expected_key_name: str):
    expected_token = f"Bearer {API_KEYS.get(expected_key_name)}"
    if token != expected_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unauthorized: Invalid token for {expected_key_name}"
        )

def log_request(endpoint: str, status_icon: str, payload: dict, error_detail: str = None):
    log_entry = {
        "time": datetime.utcnow().isoformat(),
        "endpoint": endpoint,
        "status": status_icon,
        "payload": payload
    }
    if error_detail:
        log_entry["error"] = error_detail
    add_log(log_entry)

@app.post("/uat/customers/create")
async def create_customer(data: CustomerCreate, authorization: str = Header(...)):
    endpoint = "/uat/customers/create"
    try:
        check_auth(authorization, "CUSTOMER_API_KEY")
        # Simulate some processing
        # if data.region == "Invalid":
        #    raise ValueError("Invalid region specified for customer creation")
        
        log_request(endpoint, "✅ Success", data.dict())
        return {"status": "success", "message": "Customer created successfully (UAT)"}
    except HTTPException as e:
        log_request(endpoint, "❌ Auth Failed", data.dict(), e.detail)
        raise e
    except Exception as e:
        log_request(endpoint, "💥 Error", data.dict(), str(e))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error")

@app.post("/uat/payments")
async def record_payment(data: Payment, authorization: str = Header(...)):
    endpoint = "/uat/payments"
    try:
        check_auth(authorization, "BILLING_API_KEY")
        # Simulate some processing
        # if data.amount < 0:
        #    raise ValueError("Payment amount cannot be negative")
            
        log_request(endpoint, "✅ Success", data.dict())
        return {"status": "success", "message": "Payment recorded (UAT)"}
    except HTTPException as e:
        log_request(endpoint, "❌ Auth Failed", data.dict(), e.detail)
        raise e
    except Exception as e:
        log_request(endpoint, "💥 Error", data.dict(), str(e))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error")

@app.post("/uat/chat-logs")
async def submit_chat(data: ChatLog, authorization: str = Header(...)):
    endpoint = "/uat/chat-logs"
    try:
        check_auth(authorization, "CHATLOG_API_KEY")
        # Simulate some processing
        # if len(data.message) > 500:
        #    raise ValueError("Message too long")

        log_request(endpoint, "✅ Success", data.dict())
        return {"status": "success", "message": "Chat log saved (UAT)"}
    except HTTPException as e:
        log_request(endpoint, "❌ Auth Failed", data.dict(), e.detail)
        raise e
    except Exception as e:
        log_request(endpoint, "💥 Error", data.dict(), str(e))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error")

@app.post("/uat/simulate-failure")
async def simulate_failure(authorization: str = Header(...)):
    endpoint = "/uat/simulate-failure"
    try:
        # This endpoint uses CUSTOMER_API_KEY for auth, just for consistency
        check_auth(authorization, "CUSTOMER_API_KEY") 
        
        # Intentionally raise an error to test logging
        raise ValueError("Simulated internal processing error!")
        
    except HTTPException as e:
        log_request(endpoint, "❌ Auth Failed", {"detail": "Auth attempt"}, e.detail)
        raise e
    except Exception as e:
        # Log this specific error as a '💥 Error'
        log_request(endpoint, "💥 Error", {"detail": "Simulated error triggered"}, str(e))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Simulated Error: {e}")


@app.get("/monitor", response_class=HTMLResponse)
async def monitor_ui(request: Request):
    # Optional Security from previous step
    monitor_token_env = os.getenv("MONITOR_TOKEN")
    if monitor_token_env:
        token_param = request.query_params.get("token")
        if token_param != monitor_token_env:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
            
    return templates.TemplateResponse("monitor.html", {"request": request, "logs": log_store})
