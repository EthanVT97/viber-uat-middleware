import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Viber
    VIBER_TOKEN = os.getenv("VIBER_TOKEN")  # From Viber Admin Panel
    VIBER_WEBHOOK_SECRET = os.getenv("VIBER_WEBHOOK_SECRET")

    # UAT APIs
    CUSTOMER_API_KEY = os.getenv("CUSTOMER_API_KEY", "sandbox_customer_123")
    BILLING_API_KEY = os.getenv("BILLING_API_KEY", "sandbox_billing_456")
    CHATLOG_API_KEY = os.getenv("CHATLOG_API_KEY", "sandbox_chatlog_789")

    # Monitor
    MONITOR_TOKEN = os.getenv("MONITOR_TOKEN", "shwechatuat2025")
