# Umber — Setup & Local Execution Guide

This document describes how to set up, test, and run the Umber WhatsApp Webhook server locally and connect it to Meta's WhatsApp Cloud API.

---

## 1. Environment Setup

### 1.1 Prerequisites
- Python 3.12+
- Meta for Developers account with WhatsApp Cloud API configured (Test mode)
- A tunneling utility (such as `ngrok` or `cloudflared`) to expose your local port publicly for Meta's webhooks.

### 1.2 Dependencies Installation
```bash
pip install -r requirements.txt
```

---

## 2. Configuration (`.env`)

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Populate the required credentials in `.env`:
```env
# Meta WhatsApp Cloud API credentials
WHATSAPP_TOKEN=EAAG...                 # Permanent or temporary access token from Meta App Dashboard
WHATSAPP_PHONE_NUMBER_ID=10987654321   # WhatsApp Business Phone Number ID
WHATSAPP_VERIFY_TOKEN=umber_secure_verify_token_2026 # Any custom secret token chosen by you
WHATSAPP_APP_SECRET=a1b2c3d4e5...     # Meta App Dashboard -> App Settings -> Basic -> App Secret
WHATSAPP_API_VERSION=v21.0

# YouCam API credentials
YOUCAM_API_KEY=your_youcam_api_key_here
YOUCAM_BASE_URL=https://yce-api-01.makeupar.com

# Server configuration
HOST=0.0.0.0
PORT=8000
```

---

## 3. Running the Webhook Server

Start the FastAPI application with Uvicorn:
```bash
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Verify it is running:
- Health check: `http://localhost:8000/health` -> `{"status": "ok"}`
- Root: `http://localhost:8000/` -> `{"app": "Umber", "status": "running", "stage": 1}`

---

## 4. Exposing Locally for Meta Webhooks

Meta requires a publicly accessible HTTPS endpoint for the webhook handshake.

Using **ngrok**:
```bash
ngrok http 8000
```
Copy the generated HTTPS URL (e.g., `https://abc-123.ngrok-free.app`).

Using **Cloudflare Tunnel**:
```bash
cloudflared tunnel --url http://localhost:8000
```

---

## 5. Registering the Webhook in Meta Developer Console

1. Open [Meta for Developers](https://developers.facebook.com/apps).
2. Select your App -> Navigate to **WhatsApp** in the left sidebar -> **Configuration**.
3. Under **Webhook**, click **Edit**.
4. Set **Callback URL**: `https://<your-public-domain>/webhook` (e.g. `https://abc-123.ngrok-free.app/webhook`).
5. Set **Verify Token**: Must match `WHATSAPP_VERIFY_TOKEN` in your `.env`.
6. Click **Verify and Save**. Meta will execute a `GET /webhook` handshake request.
7. Under **Webhook fields**, click **Manage** and subscribe to **`messages`**.

---

## 6. Running Tests

Run the full mocked test suite (webhook security, signatures, status handling, polling caps, error mapping, and deterministic matching):
```bash
python -m pytest tests/ -v
```

Execution evidence is automatically saved in `evidence/logs/`.
