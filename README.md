# orb-engine-core

The backend brain of **Neura-Mitram** — a FastAPI service deployed on Google
Cloud Run. Handles AI analysis (via OpenRouter), session memory (Firestore),
cognitive decay tracking, pattern detection, Mirror Mode, and the Phase 5
**Mind-Key Economy** paywall (Razorpay).

## Stack
- FastAPI + Uvicorn
- httpx (async HTTP client — also used for Razorpay REST calls)
- Firebase Admin SDK (Firestore)
- OpenRouter API (`openai/gpt-oss-120b:free` primary, `google/gemma-4-31b-it:free` fallback)
- Razorpay (Orders API + signature verification)
- Docker → Google Cloud Run

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Health check |
| POST | `/wake-mitram` | Called on page load. Returns daily directive, decay state, streak. |
| POST | `/feed-mitram` | Main analysis. Returns full reading — deep diagnostic is locked behind Phase 5. |
| POST | `/get-history` | Returns up to 90 past mood entries for the timeline chart. |
| POST | `/mirror-session` | Generates 3 pointed questions for Mirror Mode. |
| POST | `/create-order` | Phase 5. Creates a Razorpay order for a given `reading_id`. |
| POST | `/verify-payment` | Phase 5. Verifies Razorpay signature, unlocks and returns the real `deep_analysis`. |
| POST | `/razorpay-webhook` | Phase 5. Server-to-server safety net — marks a reading paid even if the client never calls `/verify-payment`. |

## Local Setup

```bash
git clone https://github.com/Neura-Mitram/orb-engine-core.git
cd orb-engine-core
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # then fill in your real keys
uvicorn main:app --reload --port 8080
```

Visit `http://localhost:8080` — you should see `{"status": "online", ...}`.

## Environment Variables

Set these in Cloud Run (Settings → Variables & Secrets), not in a committed file:

| Variable | Required | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | Yes | Free key at https://openrouter.ai/keys |
| `RAZORPAY_KEY_ID` | Yes (for Phase 5) | From Razorpay Dashboard → Settings → API Keys |
| `RAZORPAY_KEY_SECRET` | Yes (for Phase 5) | Same page — keep this one private |
| `RAZORPAY_WEBHOOK_SECRET` | Recommended | Set after configuring a webhook (see below) |

Firestore auth is automatic on Cloud Run if the service account has the
**Cloud Datastore User** role. No extra env var needed for that.
`GOOGLE_APPLICATION_CREDENTIALS` is **only** needed for local development —
never set it on Cloud Run.

## Deploy to Google Cloud Run

```bash
gcloud run deploy orb-engine-core \
  --source . \
  --region asia-south1 \
  --allow-unauthenticated \
  --set-env-vars OPENROUTER_API_KEY=your_key,RAZORPAY_KEY_ID=your_id,RAZORPAY_KEY_SECRET=your_secret \
  --memory 512Mi \
  --min-instances 0 \
  --max-instances 5
```

(Or use the Cloud Run console — Variables & Secrets tab — if you prefer the
dashboard over the CLI.)

After deploy, copy the printed **Service URL** — you'll need it in the
frontend's `app.js` as `API_BASE`.

## CORS

CORS is locked to:
```
https://neuramitram.space
https://www.neuramitram.space
```
If you deploy a different frontend domain, update `allow_origins` in `main.py`.

## Phase 5 — Razorpay Setup

1. Create a Razorpay account at https://dashboard.razorpay.com (test mode is
   instant; live mode needs KYC).
2. Settings → API Keys → Generate Test Key → copy **Key ID** and **Key Secret**.
3. Add both as Cloud Run environment variables (above).
4. (Recommended) Settings → Webhooks → Add New Webhook:
   - URL: `https://your-cloud-run-url.run.app/razorpay-webhook`
   - Active events: `payment.captured`
   - Copy the generated webhook secret → add as `RAZORPAY_WEBHOOK_SECRET`
5. Test with Razorpay's test card: `4111 1111 1111 1111`, any future expiry,
   any CVV, any OTP. Switch to live keys only once you're ready to charge
   real money.

### How the paywall actually works

- `/feed-mitram` generates the full AI reading, but the `deep_analysis` text
  is stored **server-side only** in
  `users/{user_id}/locked_readings/{reading_id}` — it is never sent to the
  browser until payment is verified. The client only receives a scrambled,
  same-length "ciphertext" preview for the blurred UI effect.
- `/create-order` creates a Razorpay order tied to that `reading_id`.
- The frontend opens Razorpay's Checkout modal directly (no backend
  round-trip needed for the modal itself).
- On success, `/verify-payment` recomputes the HMAC-SHA256 signature
  Razorpay returns and compares it server-side — only then does the real
  `deep_analysis` get released to the client.
- `/razorpay-webhook` is a safety net: if someone closes their browser
  right after paying but before the verify call fires, the webhook still
  marks the reading paid using Razorpay's own server-to-server event.

## Firestore Schema

```
users/{user_id}
  ├── mitram_state: { current_color, core_vibe, last_fed_timestamp }
  ├── recent_distress_flags: [string]      (max 5, rolling)
  ├── recent_recovery_signals: [string]    (max 5, rolling)
  ├── session_streak: number
  ├── last_session_date: "YYYY-MM-DD"
  ├── mood_history/ (subcollection)
  │     └── {auto_id}: { timestamp, orb_color, health_impact,
  │                       urgency_level, distress_flag, recovery_signal }
  └── locked_readings/ (subcollection)
        └── {reading_id}: { deep_analysis, paid, created_at, amount_paise,
                             razorpay_order_id, razorpay_payment_id, paid_at }
```

## Notes

- The AI call has automatic fallback: if `gpt-oss-120b:free` fails or rate-limits,
  it retries once on `gemma-4-31b-it:free` before erroring out.
- All AI responses are forced JSON via `response_format: {"type": "json_object"}`.
- Input is capped at 2000 characters server-side (see `FeedRequest` validator).
- If Firestore is ever unavailable, `/feed-mitram` fails open — it returns
  the real `deep_analysis` unlocked rather than blocking the product, since
  there's no way to track payment state without a database.
- To change the price, edit the single `DECRYPT_PRICE_PAISE` constant near
  the top of `main.py`.

