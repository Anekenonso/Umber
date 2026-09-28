# Umber — AI Sales Assistant for Small Retailers

> **Hackathon Submission:** YouCam API Skin AI & eCommerce VTO Hackathon (Perfect Corp / Devpost)  
> **Status:** Stage 1 Completed (Repository layout, WhatsApp webhook plumbing, HMAC-SHA256 signature verification, and test suite).

---

## The Problem & Solution

* **The Problem:** Solo and small boutique retailers selling over WhatsApp receive personalization and styling questions (*"Does this suit my tone?"*, *"What shade matches me?"*). Replies take 10+ hours on average; keyword bots fail on visual questions, causing high abandonment and low conversion.
* **The Solution:** Umber is an AI Sales Assistant on WhatsApp that requests a selfie, performs skin-tone and undertone analysis, deterministically matches curated inventory, renders a photorealistic Clothes VTO preview, and replies in real time.

---

## System Architecture

```text
Customer (WhatsApp)
   │  message / selfie
   ▼
WhatsApp Cloud API ──webhook──► app/main.py  (verify HMAC signature, parse payload)
                                   │
                                   ▼
                          app/orchestrator.py  (state machine)
                           │        │         │
             classifier.py │        │         │ store.py (SQLite: per-thread state)
             (AI: intent)  │        │
                           ▼        ▼
              clients/youcam.py   catalog/matcher.py
              (skin-tone-analysis (deterministic code)
               + cloth-v4 VTO)
                           \        /
                            ▼      ▼
                    clients/whatsapp.py ──► reply (text + image)
                                   │
                                   ▼
                          events.py (Phase 13 log) ──► evidence/logs/
```

---

## Stage 1 Progress

- [x] Restructured repository layout into clean modular architecture (`app/`, `clients/`, `catalog/`, `tests/`, `evidence/`).
- [x] Implemented Meta WhatsApp subscription verification handshake (`GET /webhook`).
- [x] Implemented HMAC-SHA256 constant-time request signature verification (`POST /webhook`) using `X-Hub-Signature-256`.
- [x] Implemented quiet status update filtering (delivered/read receipts ignored with HTTP 200).
- [x] Inbound message reception with static acknowledgment dispatch.
- [x] Built deterministic catalog matcher and 15-SKU curated collection.
- [x] Phase 13 structured event logging to `evidence/logs/events.log`.
- [x] Full test suite (13 passing tests across webhook security and core logic).

For setup instructions, see [SETUP.md](SETUP.md).
