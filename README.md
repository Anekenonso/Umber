# Umber — AI Sales Assistant for Small Retailers

> **Hackathon Submission:** YouCam API Skin AI & eCommerce VTO Hackathon (Perfect Corp / Devpost)  
> **Status:** All 6 Stages Complete (Plumbing, Classification, Skin AI, VTO Render, Escalations, Evidence Packaging & Status Dashboard). 41/41 Tests Passing.

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

## Progress Across All Stages

### Stage 1 — Webhook Plumbing & Security
- [x] Restructured repository layout into clean modular architecture (`app/`, `clients/`, `catalog/`, `tests/`, `evidence/`).
- [x] Implemented Meta WhatsApp subscription verification handshake (`GET /webhook` and root fallback).
- [x] Implemented HMAC-SHA256 constant-time request signature verification (`POST /webhook`) using `X-Hub-Signature-256`.
- [x] Implemented quiet status update filtering (delivered/read receipts ignored with HTTP 200).
- [x] Phase 13 structured event logging to `evidence/logs/events.log`.

### Stage 2 — Intent Classification & Conversation States
- [x] Phase 6 explicit conversation state machine enum (`app/states.py`).
- [x] Phase 8 deterministic guardrails: instant escalation for human requests, complaints, disputes, and refunds.
- [x] Phase 9 failure rules: automatic fallback to human escalation on ambiguous/uncertain inputs (never bury complaints).
- [x] Multi-dialect & Nigerian Pidgin code-switching support (*"Wetin go match my dark complexion abeg?"*, *"Una dey open today?"*, *"Abeg transfer me give human being"*).
- [x] Phase 12 labeled evaluation benchmark (`tests/eval_set.json`): **100% overall accuracy**, **100% escalation recall**.

### Stage 3 — Skin-Tone Analysis & Selfie Request Flow
- [x] Lightweight SQLite conversation store (`app/store.py`) tracking per-thread state and photo retries.
- [x] Graph API media downloader (`get_media_url`) for customer selfies.
- [x] Perfect Corp Facial Color Tones Analyzer integration (`task_type: skin-tone-analysis`).
- [x] Phase 9 error handling: 1 polite retake request on `error_pose` / bad angle before graceful fallback.
- [x] Phase 14 polling constraints (capped at 30 seconds / 15 attempts).

### Stage 4 — Catalog Matching & VTO Confirmation Render (`cloth-v4`)
- [x] Deterministic scoring in `app/catalog/matcher.py` ranking items by undertone, tone depth, and visual RGB contrast.
- [x] YouCam Clothes Changer (`task_type: cloth-v4`) virtual try-on render dispatch.
- [x] Dual-mode reply: WhatsApp Image message with confirmation render on success; graceful text-only recommendation on render failure or timeout (never stalls).
- [x] Post-recommendation interactions: alternative color cycling and dissatisfaction escalation.

### Stage 5 — Escalation Rules & State Persistence Hardening
- [x] All 3 escalation triggers implemented and tested: human requests, complaints, and dissatisfaction.
- [x] Post-escalation lockout guard: zero YouCam units burned and zero automated styling loops while under human review.
- [x] SQLite state persistence verified across process restarts.
- [x] Staff escalation dashboard (`GET /sessions/escalations`) and resolution endpoint (`POST /sessions/{sender_id}/resolve`).

### Stage 6 — Evidence Packaging & Production Smoke Test
- [x] Sleek judge status dashboard served at `GET /` displaying system health, architecture, and live catalog.
- [x] Evidence surface populated (`evidence/logs/`, `evidence/eval-results/`, `evidence/api-samples/`).
- [x] Complete test suite passing: **41 / 41 tests passing**.
- [x] Production smoke test checklist documented in [SETUP.md](SETUP.md).
