--- START OF FILE viber-uat-middleware-main/config.py ---

import os

class Config:
    # Default to localhost for local development, Render will override BASE_URL
    # RENDER_EXTERNAL_URL is set by Render automatically when deployed
    BASE_URL = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8000")

    # API Keys - MUST be set as environment variables in Render/Fly.io/etc.
    # Provide strong, unique keys for each environment.
    CUSTOMER_API_KEY = os.getenv("CUSTOMER_API_KEY", "sandbox_customer_123_default")
    BILLING_API_KEY = os.getenv("BILLING_API_KEY", "sandbox_billing_456_default")
    CHATLOG_API_KEY = os.getenv("CHATLOG_API_KEY", "sandbox_chatlog_789_default")

    # Monitor UI Credentials
    MONITOR_USERNAME = os.getenv("MONITOR_USERNAME", "uat_monitor_user")
    MONITOR_PASSWORD = os.getenv("MONITOR_PASSWORD", "supersecretpassword") # CHANGE THIS IN PRODUCTION/UAT

    # Viber Bot Token
    # IMPORTANT: Replace "YOUR_VIBER_BOT_TOKEN_HERE" with your actual bot token
    # Get this from your Viber Public Account settings.
    VIBER_BOT_TOKEN = os.getenv("VIBER_BOT_TOKEN", "YOUR_VIBER_BOT_TOKEN_HERE")

    # Viber Bot App Key for signature verification (if fully implemented for security)
    # This is currently not used for verification in main.py, but kept for future implementation.
    # IMPORTANT: In a real app, this MUST be a strong, randomly generated key and used for signature verification.
    VIBER_BOT_APP_KEY = os.getenv("VIBER_BOT_APP_KEY", "your_viber_app_key_placeholder") # Replace or get from env

    # Optional: Customer Agent Contact Info (if used for direct contact outside bot flow)
    CUSTOMER_AGENT_VIBER_ID = os.getenv("CUSTOMER_AGENT_VIBER_ID", "+95912345000")
    CUSTOMER_AGENT_PHONE_NUMBER = os.getenv("CUSTOMER_AGENT_PHONE_NUMBER", "+95912345000")

    # Basic check for essential keys on startup
    @classmethod
    def validate_keys(cls):
        missing_keys = []
        if not cls.CUSTOMER_API_KEY or cls.CUSTOMER_API_KEY == "sandbox_customer_123_default":
            missing_keys.append("CUSTOMER_API_KEY")
        if not cls.BILLING_API_KEY or cls.BILLING_API_KEY == "sandbox_billing_456_default":
            missing_keys.append("BILLING_API_KEY")
        if not cls.CHATLOG_API_KEY or cls.CHATLOG_API_KEY == "sandbox_chatlog_789_default":
            missing_keys.append("CHATLOG_API_KEY")
        if not cls.MONITOR_USERNAME or cls.MONITOR_USERNAME == "uat_monitor_user":
            missing_keys.append("MONITOR_USERNAME")
        if not cls.MONITOR_PASSWORD or cls.MONITOR_PASSWORD == "supersecretpassword":
            missing_keys.append("MONITOR_PASSWORD")
        if not cls.VIBER_BOT_TOKEN or cls.VIBER_BOT_TOKEN == "YOUR_VIBER_BOT_TOKEN_HERE":
            missing_keys.append("VIBER_BOT_TOKEN")

        if missing_keys:
            print("="*80)
            print("WARNING: Essential environment variables not set or using default placeholders:")
            for key in missing_keys:
                print(f"- {key}")
            print("Please ensure these are configured in your deployment environment.")
            print("="*80)

# Validate keys on import (when the app starts)
Config.validate_keys()
--- END OF FILE viber-uat-middleware-main/config.py ---
