from fastapi import FastAPI, Request, Header, HTTPException, status, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials # New import for security
from pydantic import BaseModel
from datetime import datetime
import uvicorn
import os
import secrets # New import for secure string comparison

from log_storage import add_log, log_store

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Initialize HTTPBasic for security
security = HTTPBasic()

# Load API keys from environment variables with fallback for local development
API_KEYS = {
    "CUSTOMER_API_KEY": os.getenv("CUSTOMER_API_KEY", "sandbox_customer_123"),
    "BILLING_API_KEY": os.getenv("BILLING_API_KEY", "sandbox_billing_456"),
    "CHATLOG_API_KEY": os.getenv("CHATLOG_API_KEY", "sandbox_chatlog_789")
}

# Load Monitor UI credentials from environment variables
# IMPORTANT: Provide strong default values for local development or ensure these are set in your environment
MONITOR_USERNAME = os.getenv("MONITOR_USERNAME", "uat_monitor_user")
MONITOR_PASSWORD = os.getenv("MONITOR_PASSWORD", "supersecretpassword") # Change this default for production/UAT

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

# Root endpoint for basic health check or welcome message
@app.get("/")
async def read_root():
    """
    Provides a simple welcome message for the root endpoint.
    This helps to avoid 404 Not Found errors for general requests to the base URL.
    """
    return {"message": "Viber UAT Middleware API is running. Access /monitor for live logs."}

# Endpoint for favicon.ico to prevent 404s from browsers/bots
@app.get("/favicon.ico", include_in_schema=False)
async def get_favicon():
    """
    Handles requests for favicon.ico to prevent 404 errors.
    Returns a 200 OK status, implying no specific favicon is provided.
    """
    raise HTTPException(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/uat/customers/create")
async def create_customer(data: CustomerCreate, authorization: str = Header(...)):
    endpoint = "/uat/customers/create"
    try:
        check_auth(authorization, "CUSTOMER_API_KEY")
        # Simulate some processing
        # if data.region == "Invalid":
        #    raise ValueError("Invalid region specified for customer creation")
        
        log_request(endpoint, "✅ Success", data.dict())
        # Reverted message here
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
        # Reverted message here
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
        # Reverted message here
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

# NEW: Viber Webhook endpoint
@app.post("/viber/webhook")
async def viber_webhook(request: Request):
    """
    Handles incoming Viber webhook events.
    Logs the event payload for monitoring purposes.
    """
    endpoint = "/viber/webhook"
    try:
        # Viber sends JSON payload for events
        viber_event_data = await request.json()
        
        # Log the incoming Viber event
        log_request(endpoint, "📞 Viber Event", viber_event_data)
        
        # Viber expects a 200 OK response to confirm successful receipt of the event
        return {"status": "ok"}
    except Exception as e:
        # Log any errors that occur while processing the Viber webhook
        log_request(endpoint, "💥 Viber Error", {"detail": "Failed to process Viber event"}, str(e))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to process Viber event")


# Dependency to verify monitor credentials for Basic Auth
async def verify_monitor_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, MONITOR_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, MONITOR_PASSWORD)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"}, # This header prompts the browser for login
        )
    return True

@app.get("/monitor", response_class=HTMLResponse)
async def monitor_ui(request: Request, authenticated: bool = Depends(verify_monitor_credentials)):
    # The 'authenticated' parameter will only be True if verify_monitor_credentials succeeds.
    # The old query parameter token check has been replaced by HTTP Basic Auth.
            
    return templates.TemplateResponse("monitor.html", {"request": request, "logs": log_store})
