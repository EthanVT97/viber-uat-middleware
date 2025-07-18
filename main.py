from fastapi import FastAPI, Request, Header, HTTPException, status, Depends
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, ValidationError
from datetime import datetime
import uvicorn
import os
import secrets
import httpx
import asyncio
import json

# Import configuration and logging
from config import Config
from log_storage import add_log, log_store

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Initialize HTTPBasic for security
security = HTTPBasic()

# Use values from Config class
# API Keys for internal UAT endpoints
API_KEYS = {
    "CUSTOMER_API_KEY": Config.CUSTOMER_API_KEY,
    "BILLING_API_KEY": Config.BILLING_API_KEY,
    "CHATLOG_API_KEY": Config.CHATLOG_API_KEY
}

# Monitor UI credentials
MONITOR_USERNAME = Config.MONITOR_USERNAME
MONITOR_PASSWORD = Config.MONITOR_PASSWORD

# Viber Bot Token
VIBER_BOT_TOKEN = Config.VIBER_BOT_TOKEN

# Customer Agent Contact Info (if needed, otherwise can be removed)
# CUSTOMER_AGENT_VIBER_ID = Config.CUSTOMER_AGENT_VIBER_ID
# CUSTOMER_AGENT_PHONE_NUMBER = Config.CUSTOMER_AGENT_PHONE_NUMBER

# In-memory store for user conversation states (for multi-step flows)
user_states = {} # Structure: {viber_user_id: {"state": "CURRENT_STATE", "data": {...}}}

# In-memory queue for broadcasting messages/events to agent dashboards (SSE)
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

# Agent conversation states
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

# Pydantic models for Agent Dashboard communication
class AgentSendMessage(BaseModel):
    receiver_viber_id: str
    message_text: str

class AgentEndChat(BaseModel):  # Fixed typo: Baseodel -> BaseModel
    viber_id: str

def check_auth(token: str, expected_key_name: str):
    expected_token = f"Bearer {API_KEYS.get(expected_key_name)}"  # Fixed: removed extra )
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
    # Use RENDER_EXTERNAL_URL environment variable from Render as defined in Config
    return Config.BASE_URL

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
    return {"message": "Viber UAT Middleware API is running. Access /monitor for live logs, /agent_dashboard for agent interface."}

@app.get("/health")  # Added health check endpoint
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

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
        # Intentionally raise an error to simulate an internal failure
        raise ValueError("Simulated internal processing error for UAT testing!")

    except HTTPException as e: # Re-raise HTTPExceptions (e.g., from check_auth) directly
        log_request(endpoint, "❌ Auth Failed", {"detail": "Auth attempt"}, e.detail)
        raise e
    except Exception as e: # Catch the simulated ValueError or any other unexpected error
        error_message = f"Simulated Error: {e}"
        log_request(endpoint, "💥 Error", {"detail": "Simulated error triggered"}, error_message)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=error_message)

# Helper for common "What else can I help with?" message
async def send_main_menu(sender_id: str):
    await send_viber_message(sender_id, "တခြား ဘာများ ကူညီပေးရဦးမလဲ?", MAIN_MENU_KEYBOARD)


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
            # For events without a direct sender_id (like webhook, client_status)
            return {"status": "ok", "message": "No sender ID found for state management"}

        current_user_state = user_states.get(sender_id, {"state": STATE_IDLE, "data": {}})
        current_state = current_user_state.get("state")
        user_data = current_user_state.get("data", {})

        # Handle 'conversation_started' event (user joins or bot is activated)
        if event_type == 'conversation_started':
            welcome_text = "မင်္ဂလာပါ! UAT Bot မှ ကြိုဆိုပါတယ်။ ဘယ်လိုကူညီပေးရမလဲ?"
            await send_viber_message(sender_id, welcome_text, MAIN_MENU_KEYBOARD)
            user_states[sender_id] = {"state": STATE_IDLE, "data": {}}
            print(f"Conversation started with {sender_id}. Welcome message sent.")

        # Handle 'message' event (user sends text or clicks keyboard button)
        elif event_type == 'message':
            message_type = viber_event_data.get('message', {}).get('type')

            if message_type == 'text':
                message_text = viber_event_data.get('message', {}).get('text')

                # --- Handle direct commands/menu button clicks ---
                if message_text == "start_new_customer":
                    user_states[sender_id] = {"state": STATE_COLLECTING_CUSTOMER_NAME, "data": {}}
                    await send_viber_message(sender_id, "ဖောက်သည်အသစ် ဖန်တီးပါမယ်။ ကျေးဇူးပြု၍ ဖောက်သည်၏ **အမည်** (ဥပမာ: ဦးအောင်ကျော်) ကို ထည့်သွင်းပေးပါ:")

                elif message_text == "start_record_payment":
                    user_states[sender_id] = {"state": STATE_COLLECTING_PAYMENT_USER_ID, "data": {}}
                    await send_viber_message(sender_id, "ငွေပေးချေမှု မှတ်တမ်းတင်ပါမယ်။ ကျေးဇူးပြု၍ **အသုံးပြုသူ ID** (ဥပမာ: UAT001) ကို ထည့်သွင်းပေးပါ:")

                elif message_text == "start_submit_chatlog":
                    user_states[sender_id] = {"state": STATE_COLLECTING_CHATLOG_VIBER_ID, "data": {}}
                    await send_viber_message(sender_id, "Chat Log တင်သွင်းပါမယ်။ ကျေးဇူးပြု၍ **Viber ID** (ဥပမာ: +95912345678) ကို ထည့်သွင်းပေးပါ:")

                elif message_text == "trigger_simulate_failure":
                    await send_viber_message(sender_id, "ချို့ယွင်းချက်အတုကို စတင်ဖန်တီးနေပါပြီ...")
                    result = await _trigger_simulate_failure()
                    if result and result.get("status") == "success":
                        await send_viber_message(sender_id, "✅ ချို့ယွင်းချက်အတုကို အောင်မြင်စွာ ဖန်တီးပြီးပါပြီ။")
                    else:
                        await send_viber_message(sender_id, f"💥 ချို့ယွင်းချက်အတု endpoint မှ အမှားအယွင်း ပြန်လည်ဖြေကြားပါသည်။: {result.get('message', 'အမှားအယွင်း တစ်ခုခု ဖြစ်ပွားခဲ့ပါသည်။')}")
                    user_states[sender_id] = {"state": STATE_IDLE, "data": {}}
                    await send_main_menu(sender_id)

                elif message_text == "talk_to_agent":
                    user_states[sender_id] = {"state": STATE_TALKING_TO_AGENT, "data": {}}  # Fixed: added data
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

                elif message_text == "ရပ်မည်" and current_state == STATE_TALKING_TO_AGENT:
                    user_states[sender_id] = {"state": STATE_IDLE, "data": {}} # Reset state
                    await send_viber_message(sender_id, "Customer Agent နှင့် စကားပြောဆိုခြင်းကို ရပ်နားလိုက်ပါပြီ။")
                    await send_main_menu(sender_id) # Send main menu keyboard
                    # Notify agent dashboard that conversation has ended
                    await agent_broadcast_queue.put({
                        "type": "conversation_ended",
                        "viber_id": sender_id,
                        "timestamp": datetime.utcnow().isoformat(),
                        "reason": "User ended chat"
                    })

                # --- Handle ongoing conversation states ---
                # Customer Creation Flow
                elif current_state == STATE_COLLECTING_CUSTOMER_NAME:
                    if not message_text.strip():
                        await send_viber_message(sender_id, "အမည်မထည့်ရသေးပါ။ ကျေးဇူးပြု၍ ဖောက်သည်၏ **အမည်** ကို ထည့်သွင်းပေးပါ:")
                    else:
                        user_data["name"] = message_text
                        user_states[sender_id]["data"] = user_data
                        user_states[sender_id]["state"] = STATE_COLLECTING_CUSTOMER_PHONE
                        await send_viber_message(sender_id, f"အမည်ကတော့ `{message_text}` ဖြစ်ပါတယ်။ အခု ဖောက်သည်၏ **ဖုန်းနံပါတ်** (ဥပမာ: +95912345678) ကို ထည့်သွင်းပေးပါ:")

                elif current_state == STATE_COLLECTING_CUSTOMER_PHONE:
                    # Basic validation for phone number (can be improved with regex)
                    if not message_text.strip() or not (message_text.startswith('+') and message_text[1:].isdigit()):
                        await send_viber_message(sender_id, "ဖုန်းနံပါတ် မမှန်ကန်ပါ။ ကျေးဇူးပြု၍ မှန်ကန်သော **ဖုန်းနံပါတ်** (ဥပမာ: +95912345678) ကို ထည့်သွင်းပေးပါ:")
                    else:
                        user_data["phone"] = message_text
                        user_states[sender_id]["data"] = user_data
                        user_states[sender_id]["state"] = STATE_COLLECTING_CUSTOMER_REGION
                        await send_viber_message(sender_id, f"ဖုန်းနံပါတ်ကတော့ `{message_text}` ဖြစ်ပါတယ်။ နောက်ဆုံးအနေနဲ့ ဖောက်သည်၏ **တိုင်းဒေသကြီး/ပြည်နယ်** (ဥပမာ: ရန်ကုန်၊ မန္တလေး) ကို ထည့်သွင်းပေးပါ:")

                elif current_state == STATE_COLLECTING_CUSTOMER_REGION:
                    if not message_text.strip():
                        await send_viber_message(sender_id, "တိုင်းဒေသကြီး/ပြည်နယ် မထည့်ရသေးပါ။ ကျေးဇူးပြု၍ ဖောက်သည်၏ **တိုင်းဒေသကြီး/ပြည်နယ်** ကို ထည့်သွင်းပေးပါ:")
                    else:
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
                        await send_main_menu(sender_id)

                # Payment Recording Flow
                elif current_state == STATE_COLLECTING_PAYMENT_USER_ID:
                    if not message_text.strip():
                        await send_viber_message(sender_id, "အသုံးပြုသူ ID မထည့်ရသေးပါ။ ကျေးဇူးပြု၍ **အသုံးပြုသူ ID** ကို ထည့်သွင်းပေးပါ:")
                    else:
                        user_data["user_id"] = message_text
                        user_states[sender_id]["data"] = user_data
                        user_states[sender_id]["state"] = STATE_COLLECTING_PAYMENT_AMOUNT
                        await send_viber_message(sender_id, f"အသုံးပြုသူ ID ကတော့ `{message_text}` ဖြစ်ပါတယ်။ အခု **ငွေပမာဏ** (ဥပမာ: 50000) ကို ထည့်သွင်းပေးပါ:")

                elif current_state == STATE_COLLECTING_PAYMENT_AMOUNT:
                    try:
                        amount = int(message_text.strip())
                        if amount <= 0:
                            raise ValueError("Amount must be positive")
                        user_data["amount"] = amount
                        user_states[sender_id]["data"] = user_data
                        user_states[sender_id]["state"] = STATE_COLLECTING_PAYMENT_METHOD
                        await send_viber_message(sender_id, f"ငွေပမာဏကတော့ `{amount}` ဖြစ်ပါတယ်။ အခု **ငွေပေးချေမှု နည်းလမ်း** (ဥပမာ: KBZ Pay, Wave Money, Cash) ကို ထည့်သွင်းပေးပါ:")
                    except ValueError:
                        await send_viber_message(sender_id, "ငွေပမာဏ မမှန်ကန်ပါ။ ကျေးဇူးပြု၍ မှန်ကန်သော **ငွေပမာဏ** (ဂဏန်းများသာ) ကို ထည့်သွင်းပေးပါ:")

                elif current_state == STATE_COLLECTING_PAYMENT_METHOD:
                    if not message_text.strip():
                        await send_viber_message(sender_id, "ငွေပေးချေမှု နည်းလမ်း မထည့်ရသေးပါ။ ကျေးဇူးပြု၍ **ငွေပေးချေမှု နည်းလမ်း** ကို ထည့်သွင်းပေးပါ:")
                    else:
                        user_data["method"] = message_text
                        user_states[sender_id]["data"] = user_data
                        user_states[sender_id]["state"] = STATE_COLLECTING_PAYMENT_REFERENCE_ID
                        await send_viber_message(sender_id, f"ငွေပေးချေမှု နည်းလမ်းကတော့ `{message_text}` ဖြစ်ပါတယ်။ နောက်ဆုံးအနေနဲ့ **Reference ID** (ဥပမာ: REF123456) ကို ထည့်သွင်းပေးပါ:")

                elif current_state == STATE_COLLECTING_PAYMENT_REFERENCE_ID:
                    if not message_text.strip():
                        await send_viber_message(sender_id, "Reference ID မထည့်ရသေးပါ။ ကျေးဇူးပြု၍ **Reference ID** ကို ထည့်သွင်းပေးပါ:")
                    else:
                        user_data["reference_id"] = message_text
                        user_states[sender_id]["data"] = user_data

                        await send_viber_message(sender_id, "ကျေးဇူးတင်ပါတယ်။ ငွေပေးချေမှု မှတ်တမ်းတင်နေပါပြီ...")
                        try:
                            payment_data_model = Payment(**user_data)
                            result = await _process_payment_record(payment_data_model)
                            if result and result.get("status") == "success":
                                await send_viber_message(sender_id, "✅ ငွေပေးချေမှု မှတ်တမ်းကို အောင်မြင်စွာ တင်ပြီးပါပြီ။")
                            else:
                                await send_viber_message(sender_id, f"❌ ငွေပေးချေမှု မှတ်တမ်းတင်ခြင်း မအောင်မြင်ပါ။: {result.get('message', 'အမှားအယွင်း တစ်ခုခု ဖြစ်ပွားခဲ့ပါသည်။')}")
                        except ValidationError as ex:
                            await send_viber_message(sender_id, f"ငွေပေးချေမှု အချက်အလက် ထည့်သွင်းမှု မှားယွင်းပါသည်။: {ex.errors()[0]['msg']}. ကျေးဇူးပြု၍ ထပ်မံကြိုးစားပါ။")
                        except Exception as ex:
                            print(f"Error calling _process_payment_record: {ex}")
                            await send_viber_message(sender_id, "💥 ငွေပေးချေမှု မှတ်တမ်းတင်နေစဉ် အမှားအယွင်း ဖြစ်ပွားခဲ့ပါသည်။ ကျေးဇူးပြု၍ ထပ်မံကြိုးစားပါ။")

                        user_states[sender_id] = {"state": STATE_IDLE, "data": {}}
                        await send_main_menu(sender_id)

                # Chat Log Submission Flow
                elif current_state == STATE_COLLECTING_CHATLOG_VIBER_ID:
                    if not message_text.strip():
                        await send_viber_message(sender_id, "Viber ID မထည့်ရသေးပါ။ ကျေးဇူးပြု၍ **Viber ID** ကို ထည့်သွင်းပေးပါ:")
                    else:
                        user_data["viber_id"] = message_text
                        user_states[sender_id]["data"] = user_data
                        user_states[sender_id]["state"] = STATE_COLLECTING_CHATLOG_MESSAGE
                        await send_viber_message(sender_id, f"Viber ID ကတော့ `{message_text}` ဖြစ်ပါတယ်။ အခု **Chat စာပိုဒ်** ကို ထည့်သွင်းပေးပါ:")

                elif current_state == STATE_COLLECTING_CHATLOG_MESSAGE:
                    if not message_text.strip():
                        await send_viber_message(sender_id, "Chat စာပိုဒ် မထည့်ရသေးပါ။ ကျေးဇူးပြု၍ **Chat စာပိုဒ်** ကို ထည့်သွင်းပေးပါ:")
                    else:
                        user_data["message"] = message_text
                        user_data["timestamp"] = datetime.utcnow().isoformat()
                        user_data["type"] = "user_message"
                        user_states[sender_id]["data"] = user_data

                        await send_viber_message(sender_id, "ကျေးဇူးတင်ပါတယ်။ Chat Log တင်သွင်းနေပါပြီ...")
                        try:
                            chatlog_data_model = ChatLog(**user_data)
                            result = await _process_chat_log_submission(chatlog_data_model)
                            if result and result.get("status") == "success":
                                await send_viber_message(sender_id, "✅ Chat Log ကို အောင်မြင်စွာ တင်သွင်းပြီးပါပြီ။")
                            else:
                                await send_viber_message(sender_id, f"❌ Chat Log တင်သွင်းခြင်း မအောင်မြင်ပါ။: {result.get('message', 'အမှားအယွင်း တစ်ခုခု ဖြစ်ပွားခဲ့ပါသည်။')}")
                        except ValidationError as ex:
                            await send_viber_message(sender_id, f"Chat Log အချက်အလက် ထည့်သွင်းမှု မှားယွင်းပါသည်။: {ex.errors()[0]['msg']}. ကျေးဇူးပြု၍ ထပ်မံကြိုးစားပါ။")
                        except Exception as ex:
                            print(f"Error calling _process_chat_log_submission: {ex}")
                            await send_viber_message(sender_id, "💥 Chat Log တင်သွင်းနေစဉ် အမှားအယွင်း ဖြစ်ပွားခဲ့ပါသည်။ ကျေးဇူးပြု၍ ထပ်မံကြိုးစားပါ။")

                        user_states[sender_id] = {"state": STATE_IDLE, "data": {}}
                        await send_main_menu(sender_id)

                # Agent Conversation Flow
                elif current_state == STATE_TALKING_TO_AGENT:
                    # Forward user message to agent dashboard
                    agent_message_data = {
                        "type": "user_message",
                        "viber_id": sender_id,
                        "message": message_text,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                    await agent_broadcast_queue.put(agent_message_data)
                    
                    # Log the conversation for monitoring
                    log_request("/agent/conversation", "💬 User Message", agent_message_data)
                    
                    # Send acknowledgment to user
                    await send_viber_message(sender_id, "📨 သင့်စာကို Agent ဆီပို့ပြီးပါပြီ။ ပြန်ဖြေကြားမှုအတွက် ခေတ္တစောင့်ဆိုင်းပေးပါ။")

                # Handle unrecognized commands in IDLE state
                elif current_state == STATE_IDLE:
                    unrecognized_response = (
                        f"ကျွန်ုပ် '{message_text}' ကို နားမလည်ပါဘူး။ \n"
                        "ကျေးဇူးပြု၍ အောက်ပါ menu ခလုတ်များကို အသုံးပြုပါ:"
                    )
                    await send_viber_message(sender_id, unrecognized_response, MAIN_MENU_KEYBOARD)

                # Handle unexpected states
                else:
                    await send_viber_message(sender_id, "အမှားအယွင်း ဖြစ်ပွားခဲ့ပါသည်။ ကျေးဇူးပြု၍ ပြန်လည်စတင်ပါ။")
                    user_states[sender_id] = {"state": STATE_IDLE, "data": {}}
                    await send_main_menu(sender_id)

            # Handle non-text messages
            else:
                await send_viber_message(sender_id, "ကျွန်ုပ်တို့ text message များကိုသာ လက်ခံပါသည်။ ကျေးဇူးပြု၍ text ဖြင့်ပေးပို့ပါ။")

        # Handle other event types (delivered, seen, failed, etc.)
        else:
            print(f"Received Viber event '{event_type}' from {sender_id}")

        return {"status": "ok", "message": "Event processed successfully"}

    except Exception as e:
        error_message = f"Viber webhook error: {str(e)}"
        print(error_message)
        log_request(endpoint, "💥 Webhook Error", {"error": error_message})
        return {"status": "error", "message": error_message}


# Agent Dashboard endpoints
def verify_monitor_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    is_correct_username = secrets.compare_digest(credentials.username, MONITOR_USERNAME)
    is_correct_password = secrets.compare_digest(credentials.password, MONITOR_PASSWORD)
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials

@app.get("/agent_dashboard", response_class=HTMLResponse)
async def agent_dashboard(request: Request, credentials: HTTPBasicCredentials = Depends(verify_monitor_credentials)):
    return templates.TemplateResponse("agent_dashboard.html", {"request": request})

@app.get("/agent/events")
async def agent_events_stream(credentials: HTTPBasicCredentials = Depends(verify_monitor_credentials)):
    """Server-Sent Events endpoint for agent dashboard"""
    async def event_stream():
        try:
            yield "data: {\"type\": \"connected\", \"message\": \"Agent dashboard connected\"}\n\n"
            
            while True:
                try:
                    # Wait for new events with timeout
                    event = await asyncio.wait_for(agent_broadcast_queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Send heartbeat to keep connection alive
                    yield "data: {\"type\": \"heartbeat\"}\n\n"
                except Exception as e:
                    print(f"Error in event stream: {e}")
                    break
        except Exception as e:
            print(f"Event stream error: {e}")
            yield f"data: {{\"type\": \"error\", \"message\": \"Stream error: {str(e)}\"}}\n\n"
    
    return StreamingResponse(event_stream(), media_type="text/plain")

@app.post("/agent/send_message")
async def agent_send_message(data: AgentSendMessage, credentials: HTTPBasicCredentials = Depends(verify_monitor_credentials)):
    """Endpoint for agents to send messages to users"""
    try:
        # Send message to user via Viber
        await send_viber_message(data.receiver_viber_id, data.message_text)
        
        # Log the agent message
        log_request("/agent/send_message", "📤 Agent Message", {
            "receiver_viber_id": data.receiver_viber_id,
            "message_text": data.message_text,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Broadcast to other agents (optional, for monitoring)
        await agent_broadcast_queue.put({
            "type": "agent_message",
            "viber_id": data.receiver_viber_id,
            "message": data.message_text,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        return {"status": "success", "message": "Message sent successfully"}
    
    except Exception as e:
        error_message = f"Failed to send message: {str(e)}"
        log_request("/agent/send_message", "💥 Send Error", {
            "receiver_viber_id": data.receiver_viber_id,
            "error": error_message
        })
        raise HTTPException(status_code=500, detail=error_message)

@app.post("/agent/end_chat")
async def agent_end_chat(data: AgentEndChat, credentials: HTTPBasicCredentials = Depends(verify_monitor_credentials)):
    """Endpoint for agents to end chat sessions"""
    try:
        # Reset user state
        if data.viber_id in user_states:
            user_states[data.viber_id] = {"state": STATE_IDLE, "data": {}}
        
        # Notify user that chat has ended
        await send_viber_message(data.viber_id, "Customer Agent နှင့် စကားပြောဆိုခြင်းကို ရပ်နားလိုက်ပါပြီ။")
        await send_main_menu(data.viber_id)
        
        # Log the action
        log_request("/agent/end_chat", "🔚 Chat Ended", {
            "viber_id": data.viber_id,
            "ended_by": "agent",
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Broadcast to agent dashboard
        await agent_broadcast_queue.put({
            "type": "conversation_ended",
            "viber_id": data.viber_id,
            "timestamp": datetime.utcnow().isoformat(),
            "reason": "Agent ended chat"
        })
        
        return {"status": "success", "message": "Chat ended successfully"}
    
    except Exception as e:
        error_message = f"Failed to end chat: {str(e)}"
        log_request("/agent/end_chat", "💥 End Chat Error", {
            "viber_id": data.viber_id,
            "error": error_message
        })
        raise HTTPException(status_code=500, detail=error_message)

# Monitor Dashboard (existing functionality)
@app.get("/monitor", response_class=HTMLResponse)
async def monitor_dashboard(request: Request, credentials: HTTPBasicCredentials = Depends(verify_monitor_credentials)):
    return templates.TemplateResponse("monitor.html", {"request": request})

@app.get("/monitor/logs")
async def get_logs(credentials: HTTPBasicCredentials = Depends(verify_monitor_credentials)):
    return {"logs": log_store}

@app.get("/monitor/events")
async def monitor_events_stream(credentials: HTTPBasicCredentials = Depends(verify_monitor_credentials)):
    """Server-Sent Events endpoint for monitor dashboard"""
    async def event_stream():
        try:
            yield "data: {\"type\": \"connected\", \"message\": \"Monitor connected\"}\n\n"
            
            last_log_count = len(log_store)
            while True:
                await asyncio.sleep(1)  # Check every second
                current_log_count = len(log_store)
                
                if current_log_count > last_log_count:
                    # Send new logs
                    new_logs = log_store[last_log_count:]
                    for log in new_logs:
                        yield f"data: {json.dumps(log)}\n\n"
                    last_log_count = current_log_count
                
        except Exception as e:
            print(f"Monitor event stream error: {e}")
            yield f"data: {{\"type\": \"error\", \"message\": \"Stream error: {str(e)}\"}}\n\n"
    
    return StreamingResponse(event_stream(), media_type="text/plain")

# Development server runner
if __name__ == "__main__":
    # Use environment variables for configuration
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    
    print(f"Starting Viber UAT Middleware on {host}:{port}")
    print(f"Monitor Dashboard: http://{host}:{port}/monitor")
    print(f"Agent Dashboard: http://{host}:{port}/agent_dashboard")
    
    uvicorn.run(app, host=host, port=port)
