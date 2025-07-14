from fastapi import FastAPI, Request, Header, HTTPException, status, Depends
from fastapi.responses import HTMLResponse, StreamingResponse # Added StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, ValidationError
from datetime import datetime
import uvicorn
import os
import secrets
import httpx
import asyncio
import json # For JSON encoding SSE data

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
MONITOR_USERNAME = os.getenv("MONITOR_USERNAME", "uat_monitor_user")
MONITOR_PASSWORD = os.getenv("MONITOR_PASSWORD", "supersecretpassword")

# Viber Bot Token from environment variable
VIBER_BOT_TOKEN = os.getenv("VIBER_BOT_TOKEN", "YOUR_VIBER_BOT_TOKEN_HERE")

# Customer Agent Contact Info from Environment Variables (No longer used for direct contact, but kept for context if needed elsewhere)
CUSTOMER_AGENT_VIBER_ID = os.getenv("CUSTOMER_AGENT_VIBER_ID", "+95912345000")
CUSTOMER_AGENT_PHONE_NUMBER = os.getenv("CUSTOMER_AGENT_PHONE_NUMBER", "+95912345000")

# In-memory store for user conversation states (for multi-step flows)
user_states = {} # Structure: {viber_user_id: {"state": "CURRENT_STATE", "data": {...}}}

# NEW: In-memory queue for broadcasting messages/events to agent dashboards (SSE)
agent_broadcast_queue: asyncio.Queue = asyncio.Queue()

# Define conversation states
STATE_IDLE = "IDLE"

# Customer creation states
STATE_COLLECTING_CUSTOMER_NAME = "COLLECTING_CUSTOMER_NAME"
STATE_COLLECTING_CUSTOMER_PHONE = "COLLECTING_CUSTOMER_PHONE"
STATE_COLLECTING_CUSTOMER_REGION = "COLLECTING_CUSTOMER_REGION"

# Payment recording states
STATE_COLLECTING_PAYMENT_USER_ID = "COLLECTING_PAYMENT_USER_ID"
STATE_COLLECTING_PAYMENT_AMOUNT = "COLLECTING_PAYMENT_AMOUNT"
STATE_COLLECTING_PAYMENT_METHOD = "COLLECTING_PAYMENT_METHOD"
STATE_COLLECTING_PAYMENT_REFERENCE_ID = "COLLECTING_PAYMENT_REFERENCE_ID"

# Chat log submission states
STATE_COLLECTING_CHATLOG_VIBER_ID = "COLLECTING_CHATLOG_VIBER_ID"
STATE_COLLECTING_CHATLOG_MESSAGE = "COLLECTING_CHATLOG_MESSAGE"

# NEW: Agent conversation states
STATE_TALKING_TO_AGENT = "TALKING_TO_AGENT"

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

# NEW: Pydantic models for Agent Dashboard communication
class AgentSendMessage(BaseModel):
    receiver_viber_id: str
    message_text: str

class AgentEndChat(Baseodel):
    viber_id: str

def check_auth(token: str, expected_key_name: str):
    expected_token = f"Bearer {API_KEYS.get(expected_key_name)}")
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

# Helper function to send messages back to Viber
async def send_viber_message(receiver_id: str, text: str, keyboard: dict = None):
    if not VIBER_BOT_TOKEN or VIBER_BOT_TOKEN == "YOUR_VIBER_BOT_TOKEN_HERE":
        print("Viber bot token not set. Cannot send message.")
        return

    viber_api_url = "https://chatapi.viber.com/pa/send_message"
    headers = {
        "X-Viber-Auth-Token": VIBER_BOT_TOKEN,
        "Content-Type": "application/json"
    }
    payload = {
        "receiver": receiver_id,
        "type": "text",
        "text": text
    }
    if keyboard:
        payload["keyboard"] = keyboard

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(viber_api_url, headers=headers, json=payload)
            response.raise_for_status()
            print(f"Viber message sent to {receiver_id}: {response.json()}")
        except httpx.HTTPStatusError as e:
            print(f"Error sending Viber message to {receiver_id}: {e.response.status_code} - {e.response.text}")
        except httpx.RequestError as e:
            print(f"Network error sending Viber message to {receiver_id}: {e}")

# Main Menu Keyboard with all options (Myanmarized)
MAIN_MENU_KEYBOARD = {
    "Type": "keyboard",
    "Buttons": [
        {
            "Columns": 6,
            "Rows": 1,
            "ActionType": "reply",
            "ActionBody": "start_new_customer",
            "Text": "➕ ဖောက်သည်အသစ်",
            "TextSize": "regular",
            "BgColor": "#67DD3F"
        },
        {
            "Columns": 6,
            "Rows": 1,
            "ActionType": "reply",
            "ActionBody": "start_record_payment",
            "Text": "💲 ငွေပေးချေမှု မှတ်တမ်းတင်ရန်",
            "TextSize": "regular",
            "BgColor": "#3FD0DD"
        },
        {
            "Columns": 6,
            "Rows": 1,
            "ActionType": "reply",
            "ActionBody": "start_submit_chatlog",
            "Text": "💬 Chat Log တင်သွင်းရန်",
            "TextSize": "regular",
            "BgColor": "#DD9A3F"
        },
        {
            "Columns": 6,
            "Rows": 1,
            "ActionType": "reply",
            "ActionBody": "trigger_simulate_failure",
            "Text": "💣 ချို့ယွင်းချက်အတု ဖန်တီးရန်",
            "TextSize": "regular",
            "BgColor": "#FF0000",
            "TextColor": "#FFFFFF"
        },
        { # NEW Button for Customer Agent
            "Columns": 6,
            "Rows": 1,
            "ActionType": "reply",
            "ActionBody": "talk_to_agent",
            "Text": "🧑‍💻 Customer Agent နှင့် တိုက်ရိုက်ပြောရန်",
            "TextSize": "regular",
            "BgColor": "#663399", # Purple color
            "TextColor": "#FFFFFF"
        }
    ]
}

# Helper to get the base URL for internal API calls (important for Render deployment)
def get_internal_base_url():
    # Use RENDER_EXTERNAL_URL environment variable from Render
    # Fallback to localhost for local development
    return os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8000")

# Refactored core logic functions to make internal API calls
async def _process_customer_creation(data: CustomerCreate):
    internal_auth_token = f"Bearer {API_KEYS['CUSTOMER_API_KEY']}"
    async with httpx.AsyncClient() as client:
        try:
            base_url = get_internal_base_url()
            response = await client.post(
                f"{base_url}/uat/customers/create",
                headers={"Authorization": internal_auth_token, "Content-Type": "application/json"},
                json=data.dict()
            )
            response.raise_for_status()
            log_request("/internal/customer_create_logic", "💾 Processed", data.dict())
            return response.json()
        except httpx.HTTPStatusError as e:
            log_request("/internal/customer_create_logic", "💥 API Error", data.dict(), f"HTTP Error: {e.response.status_code} - {e.response.text}")
            return {"status": "error", "message": f"API Error: {e.response.text}"}
        except Exception as e:
            log_request("/internal/customer_create_logic", "💥 Processing Error", data.dict(), str(e))
            return {"status": "error", "message": f"Internal Processing Error: {str(e)}"}

async def _process_payment_record(data: Payment):
    internal_auth_token = f"Bearer {API_KEYS['BILLING_API_KEY']}"
    async with httpx.AsyncClient() as client:
        try:
            base_url = get_internal_base_url()
            response = await client.post(
                f"{base_url}/uat/payments",
                headers={"Authorization": internal_auth_token, "Content-Type": "application/json"},
                json=data.dict()
            )
            response.raise_for_status()
            log_request("/internal/payment_record_logic", "💾 Processed", data.dict())
            return response.json()
        except httpx.HTTPStatusError as e:
            log_request("/internal/payment_record_logic", "💥 API Error", data.dict(), f"HTTP Error: {e.response.status_code} - {e.response.text}")
            return {"status": "error", "message": f"API Error: {e.response.text}"}
        except Exception as e:
            log_request("/internal/payment_record_logic", "💥 Processing Error", data.dict(), str(e))
            return {"status": "error", "message": f"Internal Processing Error: {str(e)}"}

async def _process_chat_log_submission(data: ChatLog):
    internal_auth_token = f"Bearer {API_KEYS['CHATLOG_API_KEY']}"
    async with httpx.AsyncClient() as client:
        try:
            base_url = get_internal_base_url()
            response = await client.post(
                f"{base_url}/uat/chat-logs",
                headers={"Authorization": internal_auth_token, "Content-Type": "application/json"},
                json=data.dict()
            )
            response.raise_for_status()
            log_request("/internal/chat_log_logic", "💾 Processed", data.dict())
            return response.json()
        except httpx.HTTPStatusError as e:
            log_request("/internal/chat_log_logic", "💥 API Error", data.dict(), f"HTTP Error: {e.response.status_code} - {e.response.text}")
            return {"status": "error", "message": f"API Error: {e.response.text}"}
        except Exception as e:
            log_request("/internal/chat_log_logic", "💥 Processing Error", data.dict(), str(e))
            return {"status": "error", "message": f"Internal Processing Error: {str(e)}"}

async def _trigger_simulate_failure():
    internal_auth_token = f"Bearer {API_KEYS['CUSTOMER_API_KEY']}"
    async with httpx.AsyncClient() as client:
        try:
            base_url = get_internal_base_url()
            response = await client.post(
                f"{base_url}/uat/simulate-failure",
                headers={"Authorization": internal_auth_token, "Content-Type": "application/json"},
                json={}
            )
            response.raise_for_status()
            log_request("/internal/simulate_failure_logic", "💾 Triggered", {})
            return response.json()
        except httpx.HTTPStatusError as e:
            log_request("/internal/simulate_failure_logic", "💥 API Error", {}, f"HTTP Error: {e.response.status_code} - {e.response.text}")
            return {"status": "error", "message": f"API Error: {e.response.text}"}
        except Exception as e:
            log_request("/internal/simulate_failure_logic", "💥 Processing Error", {}, str(e))
            return {"status": "error", "message": f"Internal Processing Error: {str(e)}"}


@app.get("/")
async def read_root():
    return {"message": "Viber UAT Middleware API is running. Access /monitor for live logs."}

@app.get("/favicon.ico", include_in_schema=False)
async def get_favicon():
    raise HTTPException(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/uat/customers/create")
async def create_customer(data: CustomerCreate, authorization: str = Header(...)):
    endpoint = "/uat/customers/create"
    try:
        check_auth(authorization, "CUSTOMER_API_KEY")
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
        check_auth(authorization, "CUSTOMER_API_KEY")
        raise ValueError("Simulated internal processing error!")
        
    except HTTPException as e:
        log_request(endpoint, "❌ Auth Failed", {"detail": "Auth attempt"}, e.detail)
        raise e
    except Exception as e:
        log_request(endpoint, "💥 Error", {"detail": "Simulated error triggered"}, str(e))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Simulated Error: {e}")

# UPDATED: Viber Webhook endpoint logic for comprehensive conversation flow
@app.post("/viber/webhook")
async def viber_webhook(request: Request):
    endpoint = "/viber/webhook"
    try:
        viber_event_data = await request.json()
        event_type = viber_event_data.get('event')
        
        sender_id = None
        if event_type == 'message':
            sender_id = viber_event_data.get('sender', {}).get('id')
        elif event_type == 'conversation_started':
            sender_id = viber_event_data.get('user', {}).get('id')
        elif event_type in ['delivered', 'seen', 'failed', 'subscribed', 'unsubscribed']:
            sender_id = viber_event_data.get('user_id')

        log_request(endpoint, f"📞 Viber {event_type.capitalize()}", viber_event_data)

        if not sender_id:
            return {"status": "ok", "message": "No sender ID found for state management"}

        current_user_state = user_states.get(sender_id, {"state": STATE_IDLE, "data": {}})
        current_state = current_user_state.get("state")
        user_data = current_user_state.get("data", {})

        # Handle 'conversation_started' event
        if event_type == 'conversation_started':
            welcome_text = "မင်္ဂလာပါ! UAT Bot မှ ကြိုဆိုပါတယ်။ ဘယ်လိုကူညီပေးရမလဲ?"
            await send_viber_message(sender_id, welcome_text, MAIN_MENU_KEYBOARD)
            user_states[sender_id] = {"state": STATE_IDLE, "data": {}}
            
        # Handle 'message' event (user sends text or clicks keyboard button)
        elif event_type == 'message':
            message_type = viber_event_data.get('message', {}).get('type')
            
            if message_type == 'text':
                message_text = viber_event_data.get('message', {}).get('text')
                
                # --- Handle start of new flows ---
                if message_text == "start_new_customer":
                    user_states[sender_id] = {"state": STATE_COLLECTING_CUSTOMER_NAME, "data": {}}
                    await send_viber_message(sender_id, "ဖောက်သည်အသစ် ဖန်တီးပါမယ်။ ကျေးဇူးပြု၍ ဖောက်သည်၏ **အမည်** ကို ထည့်သွင်းပေးပါ:")
                
                elif message_text == "start_record_payment":
                    user_states[sender_id] = {"state": STATE_COLLECTING_PAYMENT_USER_ID, "data": {}}
                    await send_viber_message(sender_id, "ငွေပေးချေမှု မှတ်တမ်းတင်ပါမယ်။ ကျေးဇူးပြု၍ **အသုံးပြုသူ ID** ကို ထည့်သွင်းပေးပါ:")

                elif message_text == "start_submit_chatlog":
                    user_states[sender_id] = {"state": STATE_COLLECTING_CHATLOG_VIBER_ID, "data": {}}
                    await send_viber_message(sender_id, "Chat Log တင်သွင်းပါမယ်။ ကျေးဇူးပြု၍ **Viber ID** ကို ထည့်သွင်းပေးပါ:")
                
                elif message_text == "trigger_simulate_failure":
                    await send_viber_message(sender_id, "ချို့ယွင်းချက်အတုကို စတင်ဖန်တီးနေပါပြီ...")
                    result = await _trigger_simulate_failure()
                    if result and result.get("status") == "success":
                        await send_viber_message(sender_id, "✅ ချို့ယွင်းချက်အတုကို အောင်မြင်စွာ ဖန်တီးပြီးပါပြီ။")
                    else:
                        await send_viber_message(sender_id, f"💥 ချို့ယွင်းချက်အတု endpoint မှ အမှားအယွင်း ပြန်လည်ဖြေကြားပါသည်။: {result.get('message', 'အမှားအယွင်း တစ်ခုခု ဖြစ်ပွားခဲ့ပါသည်။')}")
                    user_states[sender_id] = {"state": STATE_IDLE, "data": {}}
                    await send_viber_message(sender_id, "တခြား ဘာများ ကူညီပေးရဦးမလဲ?", MAIN_MENU_KEYBOARD)
                
                # NEW: Talk to Agent Flow
                elif message_text == "talk_to_agent":
                    # Mark user as in agent conversation mode
                    user_states[sender_id]["state"] = STATE_TALKING_TO_AGENT
                    # Notify the agent dashboard about this new conversation
                    await agent_broadcast_queue.put({
                        "type": "new_conversation",
                        "viber_id": sender_id,
                        "timestamp": datetime.utcnow().isoformat()
                    })
                    agent_message = (
                        "ယခု Customer Agent နှင့် တိုက်ရိုက်စကားပြောဆိုနိုင်ပါပြီ။\n"
                        "Agent မှ ပြန်ဖြေကြားသည်အထိ ခေတ္တစောင့်ဆိုင်းပေးပါ။\n"
                        "စကားပြောဆိုမှုကို ရပ်နားလိုပါက 'ရပ်မည်' ဟု ရိုက်ထည့်ပေးပါ။"
                    )
                    await send_viber_message(sender_id, agent_message)

                # NEW: End Chat Flow from User Side
                elif message_text == "ရပ်မည်" and current_state == STATE_TALKING_TO_AGENT:
                    user_states[sender_id] = {"state": STATE_IDLE, "data": {}} # Reset state
                    await send_viber_message(sender_id, "Customer Agent နှင့် စကားပြောဆိုခြင်းကို ရပ်နားလိုက်ပါပြီ။\nတခြား ဘာများ ကူညီပေးရဦးမလဲ?", MAIN_MENU_KEYBOARD)
                    # Notify agent dashboard that conversation has ended
                    await agent_broadcast_queue.put({
                        "type": "conversation_ended",
                        "viber_id": sender_id,
                        "timestamp": datetime.utcnow().isoformat(),
                        "reason": "User ended chat"
                    })


                # --- Handle ongoing conversation states (existing logic) ---
                # Customer Creation Flow
                elif current_state == STATE_COLLECTING_CUSTOMER_NAME:
                    user_data["name"] = message_text
                    user_states[sender_id]["data"] = user_data
                    user_states[sender_id]["state"] = STATE_COLLECTING_CUSTOMER_PHONE
                    await send_viber_message(sender_id, f"အမည်ကတော့ `{message_text}` ဖြစ်ပါတယ်။ အခု ဖောက်သည်၏ **ဖုန်းနံပါတ်** (ဥပမာ: +959xxxxxxxx) ကို ထည့်သွင်းပေးပါ:")
                
                elif current_state == STATE_COLLECTING_CUSTOMER_PHONE:
                    user_data["phone"] = message_text
                    user_states[sender_id]["data"] = user_data
                    user_states[sender_id]["state"] = STATE_COLLECTING_CUSTOMER_REGION
                    await send_viber_message(sender_id, f"ဖုန်းနံပါတ်ကတော့ `{message_text}` ဖြစ်ပါတယ်။ နောက်ဆုံးအနေနဲ့ ဖောက်သည်၏ **တိုင်းဒေသကြီး/ပြည်နယ်** (ဥပမာ: ရန်ကုန်၊ မန္တလေး) ကို ထည့်သွင်းပေးပါ:")

                elif current_state == STATE_COLLECTING_CUSTOMER_REGION:
                    user_data["region"] = message_text
                    user_states[sender_id]["data"] = user_data
                    
                    await send_viber_message(sender_id, "ကျေးဇူးတင်ပါတယ်။ ဖောက်သည်အချက်အလက်များကို ဆောင်ရွက်နေပါပြီ...")
                    try:
                        customer_data_model = CustomerCreate(**user_data)
                        result = await _process_customer_creation(customer_data_model)
                        if result and result.get("status") == "success":
                            await send_viber_message(sender_id, "✅ ဖောက်သည်ကို အောင်မြင်စွာ ဖန်တီးပြီးပါပြီ။ နောက်ထပ် ဝန်ဆောင်မှုများကို လုပ်ဆောင်နိုင်ပါပြီ။")
                        else:
                            await send_viber_message(sender_id, f"❌ ဖောက်သည်ဖန်တီးခြင်း မအောင်မြင်ပါ။: {result.get('message', 'အမှားအယွင်း တစ်ခုခု ဖြစ်ပွားခဲ့ပါသည်။')}")
                    except ValidationError as ex:
                        await send_viber_message(sender_id, f"ဖောက်သည်အချက်အလက် ထည့်သွင်းမှု မှားယွင်းပါသည်။: {ex.errors()[0]['msg']}. ကျေးဇူးပြု၍ ထပ်မံကြိုးစားပါ။")
                    except Exception as ex:
                        print(f"Error calling _process_customer_creation: {ex}")
                        await send_viber_message(sender_id, "💥 ဖောက်သည်ဖန်တီးနေစဉ် အမှားအယွင်း ဖြစ်ပွားခဲ့ပါသည်။ ကျေးဇူးပြု၍ ထပ်မံကြိုးစားပါ။")
                    
                    user_states[sender_id] = {"state": STATE_IDLE, "data": {}}
                    await send_viber_message(sender_id, "တခြား ဘာများ ကူညီပေးရဦးမလဲ?", MAIN_MENU_KEYBOARD)

                # Payment Recording Flow
                elif current_state == STATE_COLLECTING_PAYMENT_USER_ID:
                    user_data["user_id"] = message_text
                    user_states[sender_id]["data"] = user_data
                    user_states[sender_id]["state"] = STATE_COLLECTING_PAYMENT_AMOUNT
                    await send_viber_message(sender_id, f"အသုံးပြုသူ ID က `{message_text}` ဖြစ်ပါတယ်။ အခု **ပမာဏ** (ဥပမာ: 25000) ကို ထည့်သွင်းပေးပါ:")

                elif current_state == STATE_COLLECTING_PAYMENT_AMOUNT:
                    try:
                        user_data["amount"] = int(message_text)
                        user_states[sender_id]["data"] = user_data
                        user_states[sender_id]["state"] = STATE_COLLECTING_PAYMENT_METHOD
                        await send_viber_message(sender_id, f"ပမာဏက `{message_text}` ဖြစ်ပါတယ်။ ကျေးဇူးပြု၍ **ငွေပေးချေမှု နည်းလမ်း** (ဥပမာ: KBZ Pay, Wave Money) ကို ထည့်သွင်းပေးပါ:")
                    except ValueError:
                        await send_viber_message(sender_id, "ပမာဏ မမှန်ကန်ပါ။ ကျေးဇူးပြု၍ မှန်ကန်သော **ပမာဏ** ကို ဂဏန်းဖြင့် ထည့်သွင်းပေးပါ။")
                        user_states[sender_id]["state"] = STATE_COLLECTING_PAYMENT_AMOUNT

                elif current_state == STATE_COLLECTING_PAYMENT_METHOD:
                    user_data["method"] = message_text
                    user_states[sender_id]["data"] = user_data
                    user_states[sender_id]["state"] = STATE_COLLECTING_PAYMENT_REFERENCE_ID
                    await send_viber_message(sender_id, f"နည်းလမ်းက `{message_text}` ဖြစ်ပါတယ်။ နောက်ဆုံးအနေနဲ့ **Reference ID** ကို ထည့်သွင်းပေးပါ:")

                elif current_state == STATE_COLLECTING_PAYMENT_REFERENCE_ID:
                    user_data["reference_id"] = message_text
                    user_states[sender_id]["data"] = user_data

                    await send_viber_message(sender_id, "ကျေးဇူးတင်ပါတယ်။ ငွေပေးချေမှု မှတ်တမ်းတင်နေပါပြီ...")
                    try:
                        payment_data_model = Payment(**user_data)
                        result = await _process_payment_record(payment_data_model)
                        if result and result.get("status") == "success":
                            await send_viber_message(sender_id, "✅ ငွေပေးချေမှုကို အောင်မြင်စွာ မှတ်တမ်းတင်ပြီးပါပြီ။ နောက်ထပ် ဝန်ဆောင်မှုများကို လုပ်ဆောင်နိုင်ပါပြီ။")
                        else:
                            await send_viber_message(sender_id, f"❌ ငွေပေးချေမှု မှတ်တမ်းတင်ခြင်း မအောင်မြင်ပါ။: {result.get('message', 'အမှားအယွင်း တစ်ခုခု ဖြစ်ပွားခဲ့ပါသည်။')}")
                    except ValidationError as ex:
                        await send_viber_message(sender_id, f"ငွေပေးချေမှုအချက်အလက် ထည့်သွင်းမှု မှားယွင်းပါသည်။: {ex.errors()[0]['msg']}. ကျေးဇူးပြု၍ ထပ်မံကြိုးစားပါ။")
                    except Exception as ex:
                        print(f"Error calling _process_payment_record: {ex}")
                        await send_viber_message(sender_id, "💥 ငွေပေးချေမှု မှတ်တမ်းတင်နေစဉ် အမှားအယွင်း ဖြစ်ပွားခဲ့ပါသည်။ ကျေးဇူးပြု၍ ထပ်မံကြိုးစားပါ။")
                    
                    user_states[sender_id] = {"state": STATE_IDLE, "data": {}}
                    await send_viber_message(sender_id, "တခြား ဘာများ ကူညီပေးရဦးမလဲ?", MAIN_MENU_KEYBOARD)

                # Chat Log Submission Flow
                elif current_state == STATE_COLLECTING_CHATLOG_VIBER_ID:
                    user_data["viber_id"] = message_text
                    user_states[sender_id]["data"] = user_data
                    user_states[sender_id]["state"] = STATE_COLLECTING_CHATLOG_MESSAGE
                    await send_viber_message(sender_id, f"Viber ID က `{message_text}` ဖြစ်ပါတယ်။ အခု **Chat မက်ဆေ့ခ်ျ** ကို ထည့်သွင်းပေးပါ:")

                elif current_state == STATE_COLLECTING_CHATLOG_MESSAGE:
                    user_data["message"] = message_text
                    user_states[sender_id]["data"] = user_data
                    
                    # Add fixed/auto-generated fields for ChatLog
                    user_data["timestamp"] = datetime.utcnow().isoformat()
                    user_data["type"] = "user_input"

                    await send_viber_message(sender_id, "ကျေးဇူးတင်ပါတယ်။ Chat Log တင်သွင်းနေပါပြီ...")
                    try:
                        chatlog_data_model = ChatLog(**user_data)
                        result = await _process_chat_log_submission(chatlog_data_model)
                        if result and result.get("status") == "success":
                            await send_viber_message(sender_id, "✅ Chat Log ကို အောင်မြင်စွာ တင်သွင်းပြီးပါပြီ။ နောက်ထပ် ဝန်ဆောင်မှုများကို လုပ်ဆောင်နိုင်ပါပြီ။")
                        else:
                            await send_viber_message(sender_id, f"❌ Chat Log တင်သွင်းခြင်း မအောင်မြင်ပါ။: {result.get('message', 'အမှားအယွင်း တစ်ခုခု ဖြစ်ပွားခဲ့ပါသည်။')}")
                    except ValidationError as ex:
                        await send_viber_message(sender_id, f"Chat Log အချက်အလက် ထည့်သွင်းမှု မှားယွင်းပါသည်။: {ex.errors()[0]['msg']}. ကျေးဇူးပြု၍ ထပ်မံကြိုးစားပါ။")
                    except Exception as ex:
                        print(f"Error calling _process_chat_log_submission: {ex}")
                        await send_viber_message(sender_id, "💥 Chat Log တင်သွင်းနေစဉ် အမှားအယွင်း ဖြစ်ပွားခဲ့ပါသည်။ ကျေးဇူးပြု၍ ထပ်မံကြိုးစားပါ။")
                    
                    user_states[sender_id] = {"state": STATE_IDLE, "data": {}}
                    await send_viber_message(sender_id, "တခြား ဘာများ ကူညီပေးရဦးမလဲ?", MAIN_MENU_KEYBOARD)

                # NEW: If user is in agent mode and sends a message, forward to agent
                elif current_state == STATE_TALKING_TO_AGENT:
                    message_for_agent = {
                        "type": "new_message",
                        "sender_id": sender_id,
                        "message_text": message_text,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                    await agent_broadcast_queue.put(message_for_agent)
                    print(f"User {sender_id} message to agent: {message_text}")
                    # Acknowledge to user that message is being forwarded
                    await send_viber_message(sender_id, "သင့်မက်ဆေ့ခ်ျကို Customer Agent ထံ ပို့လိုက်ပါပြီ။ ခေတ္တစောင့်ဆိုင်းပေးပါ။")
                    

                # Default message for unhandled text in IDLE state
                elif current_state == STATE_IDLE:
                    await send_viber_message(sender_id, "နားမလည်ပါဘူး။ ကျေးဇူးပြု၍ menu မှ ရွေးချယ်ပေးပါ:", MAIN_MENU_KEYBOARD)

        return {"status": "ok"}
    except Exception as e:
        log_request(endpoint, "💥 Viber Error", {"detail": "Failed to process Viber event"}, str(e))
        return {"status": "error", "message": "Internal server error"}


# Dependency to verify monitor credentials for Basic Auth
async def verify_monitor_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, MONITOR_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, MONITOR_PASSWORD)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True

@app.get("/monitor", response_class=HTMLResponse)
async def monitor_ui(request: Request, authenticated: bool = Depends(verify_monitor_credentials)):
    return templates.TemplateResponse("monitor.html", {"request": request, "logs": log_store})


# NEW: Agent Dashboard UI Endpoint
@app.get("/agent_dashboard", response_class=HTMLResponse)
async def agent_dashboard_ui(request: Request, authenticated: bool = Depends(verify_monitor_credentials)):
    """
    Displays the Agent Dashboard for real-time chat with users.
    """
    return templates.TemplateResponse("agent_dashboard.html", {"request": request})

# NEW: Server-Sent Events (SSE) Endpoint for Agent Dashboard
@app.get("/agent_dashboard/stream")
async def agent_dashboard_stream(authenticated: bool = Depends(verify_monitor_credentials)):
    """
    Streams new messages from users to the agent dashboard using Server-Sent Events.
    """
    async def event_generator():
        while True:
            try:
                # Wait for a new message or conversation update from the bot's processing
                event_data = await agent_broadcast_queue.get()
                yield f"data: {json.dumps(event_data)}\n\n" # SSE format: data: {json}\n\n
            except asyncio.CancelledError:
                # Client (browser) disconnected
                break
            except Exception as e:
                # Log any errors and continue to prevent stream from breaking
                print(f"Error in SSE stream: {e}")
                # Optional: yield an error message to client
                # yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                await asyncio.sleep(1) # Prevent busy loop on error

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# NEW: Endpoint for Agent to send messages back to user
@app.post("/agent_dashboard/send_message")
async def send_message_from_agent(message: AgentSendMessage, authenticated: bool = Depends(verify_monitor_credentials)):
    """
    Allows an agent to send a message to a specific Viber user.
    """
    try:
        # Send message to user via Viber API
        await send_viber_message(message.receiver_viber_id, message.message_text)
        
        # Log this action
        log_request("/agent_dashboard/send_message", "➡️ Agent Reply", {
            "receiver_id": message.receiver_viber_id,
            "message": message.message_text
        })
        return {"status": "success", "message": "Message sent to user"}
    except Exception as e:
        log_request("/agent_dashboard/send_message", "💥 Agent Send Error", {
            "receiver_id": message.receiver_viber_id,
            "message": message.message_text
        }, str(e))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to send message: {e}")

# NEW: Endpoint for Agent to end a chat
@app.post("/agent_dashboard/end_chat")
async def end_chat_from_agent(data: AgentEndChat, authenticated: bool = Depends(verify_monitor_credentials)):
    """
    Allows an agent to manually end a chat session with a user.
    """
    viber_id = data.viber_id
    if viber_id in user_states and user_states[viber_id]["state"] == STATE_TALKING_TO_AGENT:
        user_states[viber_id]["state"] = STATE_IDLE # Reset user state to idle
        user_states[viber_id]["data"] = {} # Clear any partial data
        
        # Notify user that chat is ended
        await send_viber_message(viber_id, "Customer Agent မှ စကားပြောဆိုမှုကို ရပ်နားလိုက်ပါပြီ။ တခြား ဘာများ ကူညီပေးရဦးမလဲ?", MAIN_MENU_KEYBOARD)
        
        # Notify agent dashboards that this conversation is ended
        await agent_broadcast_queue.put({
            "type": "conversation_ended",
            "viber_id": viber_id,
            "timestamp": datetime.utcnow().isoformat(),
            "reason": "Agent ended chat"
        })
        
        log_request("/agent_dashboard/end_chat", "🛑 Chat Ended", {"viber_id": viber_id})
        return {"status": "success", "message": "Chat session ended for user"}
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found or not in active chat.")