# Umber — Judge Evidence & Media Pack

This folder contains media assets and conversation captures demonstrating the live Umber WhatsApp sales assistant workflow for the **YouCam API Skin AI & eCommerce VTO Hackathon**.

## Flow Highlights
1. **Inbound Personalization Prompt:** Customer inquires about best-matching outfit for their complexion (including Nigerian Pidgin code-switching).
2. **Selfie Intake & State Progression:** Assistant requests a natural light selfie, advancing to `AWAITING_PHOTO` and `ANALYZING`.
3. **Skin-Tone AI & Deterministic Match:** YouCam `skin-tone-analysis` extracts HEX and undertone; deterministic catalog scoring selects the optimal merchant SKU.
4. **VTO Confirmation Render:** YouCam `cloth-v4` renders the garment onto the customer selfie, returned with price and description.
5. **Alternative Request / Escalation:** Demonstrating graceful text fallback, alternative browsing, or post-escalation lockout to prevent automated state corruption.

See `evidence/api-samples/` for raw API response contracts and `evidence/logs/` for complete audit traces.
