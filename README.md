--- START OF FILE viber-uat-middleware-main/README.md ---
# Viber UAT Middleware

This project is a FastAPI application acting as a middleware for Viber bot User Acceptance Testing (UAT). It simulates interactions with backend APIs (Customer, Billing, Chat Log) and provides a monitoring dashboard and an agent chat interface.

## Features

*   **Viber Bot Integration:** Handles Viber webhooks for messages and conversation events.
*   **Interactive Forms:** Guides users through multi-step forms (e.g., creating a new customer, recording payments, submitting chat logs) using quick-reply buttons and conversational prompts.
*   **Backend API Simulation:** Mocks API calls to Customer, Billing, and Chat Log services for UAT purposes.
*   **Simulated Failure:** An endpoint to trigger a simulated internal error for testing error handling.
*   **Live Log Monitor:** A web-based dashboard (`/monitor`) to view real-time logs of all incoming Viber events and outgoing internal API calls. Protected by Basic Authentication.
*   **Agent Dashboard:** A real-time chat interface (`/agent_dashboard`) for human agents to interact directly with Viber users who request to "talk to an agent". Uses Server-Sent Events (SSE) for live updates. Protected by Basic Authentication.
*   **Responsive UI:** Agent Dashboard is designed to be responsive.

## Getting Started

### Prerequisites

*   Python 3.10+
*   Docker (Optional, but recommended for deployment consistency)
*   Git
*   A Viber Public Account and Bot Token

### Local Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/viber-uat-middleware-main.git
    cd viber-uat-middleware-main
    ```

2.  **Create and activate a virtual environment:**
    ```bash
    python -m venv venv
    # On Windows:
    # .\venv\Scripts\activate
    # On macOS/Linux:
    source venv/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Set Environment Variables:**
    Create a `.env` file in the root directory (or set them directly in your shell). **Do NOT commit `.env` files to Git.**

    ```dotenv
    # .env example
    CUSTOMER_API_KEY="your_customer_uat_key"
    BILLING_API_KEY="your_billing_uat_key"
    CHATLOG_API_KEY="your_chatlog_uat_key"
    MONITOR_USERNAME="uat_monitor_user" # Change this for production/UAT
    MONITOR_PASSWORD="supersecretpassword" # Change this for production/UAT
    VIBER_BOT_TOKEN="YOUR_VIBER_BOT_TOKEN_HERE" # Get this from your Viber Public Account
    # RENDER_EXTERNAL_URL is set by Render automatically. For local, it defaults to http://localhost:8000
    ```
    **Important:** For actual UAT, replace `your_customer_uat_key`, etc., and especially `MONITOR_PASSWORD` and `VIBER_BOT_TOKEN` with strong, unique values.

5.  **Run the application locally:**
    ```bash
    uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
    ```
    The application will be running at `http://localhost:8000`.

### Deployment to Render

This application is configured for easy deployment on [Render.com](https://render.com/) using a `Dockerfile`.

1.  **Create a Render Account:** If you don't have one, sign up at [Render.com](https://render.com/).
2.  **Connect GitHub:** Connect your GitHub account to Render.
3.  **Create a New Web Service:**
    *   From your Render Dashboard, click "New" -> "Web Service".
    *   Select your GitHub repository (e.g., `your-username/viber-uat-middleware-main`).
    *   **Service Name:** Choose a name (e.g., `viber-uat-middleware`).
    *   **Region:** Select a region close to your users or Viber's servers.
    *   **Branch:** `main` (or your preferred deployment branch).
    *   **Root Directory:** Leave empty unless your code is in a subdirectory.
    *   **Runtime:** `Docker` (Render will automatically detect your `Dockerfile`).
    *   **Build Command:** (Leave empty, Dockerfile handles it)
    *   **Start Command:** (Leave empty, Dockerfile `CMD` handles it)
    *   **Plan:** Choose a suitable plan (e.g., "Starter" for UAT).
4.  **Add Environment Variables:**
    This is crucial. Go to the "Environment" section of your Web Service settings in Render and add the following variables. These should **not** be the default placeholder values from `.env`.

    *   `CUSTOMER_API_KEY`: Your UAT Customer Service API Key.
    *   `BILLING_API_KEY`: Your UAT Billing Service API Key.
    *   `CHATLOG_API_KEY`: Your UAT Chat Log Service API Key.
    *   `MONITOR_USERNAME`: Username for accessing monitor and agent dashboards.
    *   `MONITOR_PASSWORD`: Strong password for accessing monitor and agent dashboards.
    *   `VIBER_BOT_TOKEN`: Your actual Viber Public Account Bot Token.
    *   `RENDER_EXTERNAL_URL`: This is automatically set by Render to your service's public URL (e.g., `https://viber-uat-middleware.onrender.com`). The `config.py` uses this to correctly form internal API call URLs.

5.  **Deploy:** Click "Create Web Service". Render will build and deploy your application.

### Configure Viber Webhook

1.  Once your Render service is deployed, get its public URL (e.g., `https://viber-uat-middleware.onrender.com`).
2.  Your Viber webhook URL will be `YOUR_RENDER_URL/viber/webhook`. For example: `https://viber-uat-middleware.onrender.com/viber/webhook`.
3.  Go to your Viber Public Account settings (usually on the Viber Admin Panel).
4.  Find the Webhook URL setting and paste your deployed service's webhook URL there.

## Usage

### Viber Bot Interaction

*   **Start a conversation:** Find your bot in Viber and send a message or start a chat. You should receive a welcome message and a keyboard with options.
*   **Use Buttons:** Click the buttons on the keyboard to initiate flows like "ဖောက်သည်အသစ်" (New Customer), "ငွေပေးချေမှု မှတ်တမ်းတင်ရန်" (Record Payment), etc.
*   **Follow Prompts:** The bot will guide you step-by-step to collect necessary information.
*   **Talk to Agent:** Click "🧑‍💻 Customer Agent နှင့် တိုက်ရိုက်ပြောရန်" to enter agent chat mode. Type your messages to the agent. To end the chat, type "ရပ်မည်".

### Monitor UI

Access the live log monitor at `YOUR_RENDER_URL/monitor` (e.g., `https://viber-uat-middleware.onrender.com/monitor`). You will be prompted for the `MONITOR_USERNAME` and `MONITOR_PASSWORD` you set.

### Agent Dashboard

Access the agent chat dashboard at `YOUR_RENDER_URL/agent_dashboard` (e.g., `https://viber-uat-middleware.onrender.com/agent_dashboard`). You will also be prompted for the `MONITOR_USERNAME` and `MONITOR_PASSWORD`. Agents can see live conversations and reply to users.
--- END OF FILE viber-uat-middleware-main/README.md ---
