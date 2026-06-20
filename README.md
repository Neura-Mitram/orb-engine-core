# orb-engine-core

The backend brain of **Neura-Mitram** — a FastAPI service deployed on Google
Cloud Run. Handles AI analysis (via OpenRouter), session memory (Firestore),
cognitive decay tracking, pattern detection, and the Mirror Mode question
engine.

## Stack
- FastAPI + Uvicorn
- httpx (async HTTP client)
- Firebase Admin SDK (Firestore)
- OpenRouter API (`openai/gpt-oss-120b:free` primary, `google/gemma-4-31b-it:free` fallback)
- Docker → Google Cloud Run

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Health check |
| POST | `/wake-mitram` | Called on page load. Returns daily directive, decay state, streak. |
| POST | `/feed-mitram` | Main analysis. Takes user journal text, returns full psychological reading. |
| POST | `/get-history` | Returns up to 90 past mood entries for the timeline chart. |
| POST | `/mirror-session` | Generates 3 pointed questions for Mirror Mode. |

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

- `OPENROUTER_API_KEY` — required. Get one free at https://openrouter.ai/keys
- Firestore auth is automatic on Cloud Run if the service account has the
  **Cloud Datastore User** role. No extra env var needed there.

## Deploy to Google Cloud Run

```bash
gcloud run deploy orb-engine-core \
  --source . \
  --region asia-south1 \
  --allow-unauthenticated \
  --set-env-vars OPENROUTER_API_KEY=your_key_here \
  --memory 512Mi \
  --min-instances 0 \
  --max-instances 5
```

After deploy, copy the printed **Service URL** — you'll need it in the
frontend's `app.js` as `API_BASE`.

## CORS

CORS is locked to:
```
https://neuramitram.space
https://www.neuramitram.space
```
If you deploy a different frontend domain, update `allow_origins` in `main.py`.

## Firestore Schema

```
users/{user_id}
  ├── mitram_state: { current_color, core_vibe, last_fed_timestamp }
  ├── recent_distress_flags: [string]      (max 5, rolling)
  ├── recent_recovery_signals: [string]    (max 5, rolling)
  ├── session_streak: number
  ├── last_session_date: "YYYY-MM-DD"
  └── mood_history/ (subcollection)
        └── {auto_id}: { timestamp, orb_color, health_impact,
                          urgency_level, distress_flag, recovery_signal }
```

## Notes

- The AI call has automatic fallback: if `gpt-oss-120b:free` fails or rate-limits,
  it retries once on `gemma-4-31b-it:free` before erroring out.
- All AI responses are forced JSON via `response_format: {"type": "json_object"}`.
- Input is capped at 2000 characters server-side (see `FeedRequest` validator).
