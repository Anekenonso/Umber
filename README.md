# Umber — AI Sales Assistant for Small Retailers

> **Hackathon Submission:** YouCam API Skin AI & eCommerce VTO Hackathon (Perfect Corp / Devpost)  
> **Status:** Stage 2 Completed (Intent Classification, Explicit State Machine, Nigerian Pidgin & Edge Case Handling, 100% Escalation Recall).

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

## Progress by Stage

### Stage 1 — Webhook Plumbing & Security
- [x] Restructured repository layout into clean modular architecture (`app/`, `clients/`, `catalog/`, `tests/`, `evidence/`).
- [x] Implemented Meta WhatsApp subscription verification handshake (`GET /webhook` and root fallback).
- [x] Implemented HMAC-SHA256 constant-time request signature verification (`POST /webhook`) using `X-Hub-Signature-256`.
- [x] Implemented quiet status update filtering (delivered/read receipts ignored with HTTP 200).
- [x] Inbound message reception with static acknowledgment dispatch.
- [x] Built deterministic catalog matcher and 15-SKU curated collection.
- [x] Phase 13 structured event logging to `evidence/logs/events.log`.

### Stage 2 — Intent Classification & Conversation States
- [x] Phase 6 explicit conversation state machine enum (`app/states.py`).
- [x] Phase 8 deterministic guardrails: instant escalation for human requests, complaints, disputes, and refunds.
- [x] Phase 9 failure rules: automatic fallback to human escalation on ambiguous/uncertain inputs (never bury complaints).
- [x] Multi-dialect & Nigerian Pidgin code-switching support (*"Wetin go match my dark complexion abeg?"*, *"Una dey open today?"*, *"Abeg transfer me give human being"*).
- [x] Phase 12 labeled evaluation benchmark (`tests/eval_set.json`): **100% overall accuracy**, **100% escalation recall**.
- [x] Full test suite: **23/23 tests passing** (`tests/test_classifier.py`, `tests/test_webhook.py`, `tests/test_logic.py`).
- [x] Webhook integration: dynamic intent-driven routing (`personalization` -> selfie prompt, `general` -> store FAQ assistance, `escalation` -> human handoff).

For setup instructions, see [SETUP.md](SETUP.md).
