import os

class Config:
    # Default to localhost for local development, Render will override BASE_URL
    BASE_URL = os.getenv("BASE_URL", "http://localhost:10000")

    # API Keys - MUST be set as Render environment variables
    CUSTOMER_API_KEY = os.getenv("CUSTOMER_API_KEY")
    BILLING_API_KEY = os.getenv("BILLING_API_KEY")
    MONITOR_TOKEN = os.getenv("MONITOR_TOKEN")

    # Viber Bot App Key for signature verification (if fully implemented)
    # IMPORTANT: In a real app, this MUST be a strong, randomly generated key.
    # This is a placeholder for your actual Viber Bot application key.
    VIBER_BOT_APP_KEY = os.getenv("VIBER_BOT_APP_KEY", "your_viber_app_key_here") # Replace with your actual key or get from env

    if not CUSTOMER_API_KEY or not BILLING_API_KEY or not MONITOR_TOKEN:
        print("WARNING: API keys or Monitor Token not set in environment variables. This might cause issues.")
