import os
import json
import hmac
import hashlib
import uuid
import random
from datetime import datetime, timezone, date, timedelta
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, validator
import firebase_admin
from firebase_admin import firestore
import httpx

# ─────────────────────────────────────────────
#  APP INIT
# ─────────────────────────────────────────────
app = FastAPI(title="Neura-Mitram Core Engine v2.1 — Phase 5 Mind-Key Economy")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://neuramitram.space",
        "https://www.neuramitram.space",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────
#  CONSTANTS
# ─────────────────────────────────────────────
PRIMARY_MODEL  = "openai/gpt-oss-120b:free"
FALLBACK_MODEL = "google/gemma-4-31b-it:free"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

RAZORPAY_ORDERS_URL = "https://api.razorpay.com/v1/orders"
DECRYPT_PRICE_PAISE = 4900  # ₹49.00 — change this single line to reprice
CIPHER_CHARS = "ABCDEF0123456789#$%&@*XQZ"

DISTRESS_FLAGS = (
    "none|insomnia|relationship_toxicity|burnout|general_anxiety"
    "|grief|loneliness|decision_paralysis|physical_exhaustion"
    "|creative_block|financial_stress|identity_crisis"
)
RECOVERY_SIGNALS = (
    "none|clarity|acceptance|motivation|emotional_release|breakthrough|gratitude"
)

# ─────────────────────────────────────────────
#  FIRESTORE
# ─────────────────────────────────────────────
_db = None

def get_db():
    global _db
    if _db is None:
        try:
            if not firebase_admin._apps:
                firebase_admin.initialize_app()
            _db = firestore.client()
            print("✓ Firestore connected.")
        except Exception as e:
            print(f"✗ Firestore init failed: {e}")
    return _db

# ─────────────────────────────────────────────
#  REQUEST MODELS
# ─────────────────────────────────────────────
class FeedRequest(BaseModel):
    user_id:    str
    user_input: str

    @validator("user_input")
    def validate_input(cls, v):
        v = v.strip()
        if len(v) < 3:
            raise ValueError("Input too short.")
        if len(v) > 2000:
            raise ValueError("Input too long (max 2000 chars).")
        return v

class WakeRequest(BaseModel):
    user_id: str

class HistoryRequest(BaseModel):
    user_id: str
    limit:   int = 30

class CreateOrderRequest(BaseModel):
    user_id:    str
    reading_id: str

class VerifyPaymentRequest(BaseModel):
    user_id:              str
    reading_id:            str
    razorpay_order_id:     str
    razorpay_payment_id:   str
    razorpay_signature:    str

# ─────────────────────────────────────────────
#  OPENROUTER HELPER  (async + fallback)
# ─────────────────────────────────────────────
async def call_openrouter(key: str, system_prompt: str, user_message: str = "") -> dict:
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type":  "application/json",
        "HTTP-Referer":  "https://neuramitram.space",
        "X-Title":       "Neura-Mitram",
    }
    messages = [{"role": "system", "content": system_prompt}]
    if user_message:
        messages.append({"role": "user", "content": user_message})

    payload = {
        "model":           PRIMARY_MODEL,
        "messages":        messages,
        "response_format": {"type": "json_object"},
        "temperature":     0.75,
        "max_tokens":      600,
    }

    async with httpx.AsyncClient(timeout=35) as client:
        r = await client.post(OPENROUTER_URL, headers=headers, json=payload)

        if r.status_code != 200:
            # Fallback to secondary model
            payload["model"] = FALLBACK_MODEL
            r = await client.post(OPENROUTER_URL, headers=headers, json=payload)
            if r.status_code != 200:
                raise HTTPException(502, f"Both AI models unavailable. Status: {r.status_code}")

        raw = r.json()["choices"][0]["message"]["content"]
        # Strip any accidental markdown fences
        raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        return json.loads(raw)


# ─────────────────────────────────────────────
#  PHASE 5 HELPERS — Mind-Key Economy
# ─────────────────────────────────────────────
def scramble_text(text: str) -> str:
    """
    Produces a same-shape 'ciphertext' preview of locked text —
    preserves spacing/punctuation/length so the blurred UI looks
    like real encrypted output, without ever exposing real content.
    """
    return "".join(
        random.choice(CIPHER_CHARS) if c.isalnum() else c
        for c in text
    )


async def create_razorpay_order(key_id: str, key_secret: str, reading_id: str, user_id: str) -> dict:
    payload = {
        "amount":          DECRYPT_PRICE_PAISE,
        "currency":        "INR",
        "receipt":         reading_id,
        "payment_capture": 1,
        "notes": {
            "user_id":    user_id,
            "reading_id": reading_id,
            "product":    "neura_mitram_diagnostic_decrypt",
        },
    }
    async with httpx.AsyncClient(timeout=15, auth=(key_id, key_secret)) as client:
        r = await client.post(RAZORPAY_ORDERS_URL, json=payload)
        if r.status_code not in (200, 201):
            raise HTTPException(502, f"Razorpay order creation failed: {r.text}")
        return r.json()

# ─────────────────────────────────────────────
#  ROUTES
# ─────────────────────────────────────────────

@app.get("/")
def health():
    return {
        "status":        "online",
        "version":       "2.1",
        "primary_model": PRIMARY_MODEL,
        "fallback":      FALLBACK_MODEL,
    }


@app.post("/wake-mitram")
async def wake_mitram(request: WakeRequest):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise HTTPException(500, "OPENROUTER_API_KEY not set.")

    db = get_db()
    flag_history   = []
    decay_state    = False
    decay_hours    = 0.0
    session_streak = 0
    dominant_flag  = None
    escalation_mode = False

    if db:
        try:
            ref = db.collection("users").document(request.user_id)
            doc = ref.get()

            if doc.exists:
                data           = doc.to_dict()
                flag_history   = data.get("recent_distress_flags", [])
                session_streak = data.get("session_streak", 0)
                today          = date.today().isoformat()
                yesterday      = (date.today() - timedelta(days=1)).isoformat()
                last_date      = data.get("last_session_date", "")

                # ── Streak tracking ──
                if last_date == today:
                    pass  # Already counted today
                elif last_date == yesterday:
                    session_streak += 1
                    ref.set(
                        {"session_streak": session_streak, "last_session_date": today},
                        merge=True
                    )
                else:
                    session_streak = 1
                    ref.set(
                        {"session_streak": 1, "last_session_date": today},
                        merge=True
                    )

                # ── Cognitive decay ──
                ts = data.get("mitram_state", {}).get("last_fed_timestamp")
                if ts:
                    last_fed    = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    decay_hours = (datetime.now(timezone.utc) - last_fed).total_seconds() / 3600
                    if decay_hours > 168:
                        decay_state = "death"
                    elif decay_hours > 48:
                        decay_state = "critical"
                    elif decay_hours > 24:
                        decay_state = "warning"

            # ── Pattern detection ──
            active = [f for f in flag_history if f != "none"]
            if active:
                dominant_flag = max(set(active), key=active.count)
                if active.count(dominant_flag) >= 3:
                    escalation_mode = True

        except Exception as e:
            print(f"Wake fetch error: {e}")

    # ── Generate directive ──
    directive = "SYSTEM AWAKE. WAITING FOR INITIAL NEURAL CALIBRATION."

    if flag_history:
        if escalation_mode and dominant_flag:
            system_prompt = (
                f"You are Mitram — the part of the user's mind they avoid. "
                f"The user has flagged '{dominant_flag}' "
                f"{flag_history.count(dominant_flag)}/{len(flag_history)} recent sessions. "
                f"This is a chronic pattern, not a passing emotion. "
                f"Give one razor-sharp directive addressing this pattern head-on. No comfort. No softening. "
                f'Output ONLY this JSON: {{"directive": "your message here"}}'
            )
        else:
            history_str = ", ".join(flag_history)
            system_prompt = (
                f"You are Mitram — the part of the user's mind they avoid. "
                f"Recent psychological states: [{history_str}]. "
                f"Give one sharp 1-line morning directive. Name what they're carrying. No sugarcoating. "
                f'Output ONLY this JSON: {{"directive": "your message here"}}'
            )

        try:
            ai = await call_openrouter(key, system_prompt)
            directive = ai.get("directive", directive)
        except Exception as e:
            print(f"Directive generation failed: {e}")
            directive = "CONNECTION UNSTABLE. RAW INPUT REQUIRED TO CALIBRATE."

    return {
        "directive":        directive.upper(),
        "decay_state":      decay_state,
        "decay_hours":      round(decay_hours, 1),
        "session_streak":   session_streak,
        "dominant_flag":    dominant_flag,
        "escalation_mode":  escalation_mode,
    }


@app.post("/feed-mitram")
async def feed_mitram(request: FeedRequest):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise HTTPException(500, "OPENROUTER_API_KEY not set.")

    db = get_db()
    flag_history     = []
    recovery_history = []

    if db:
        try:
            doc = db.collection("users").document(request.user_id).get()
            if doc.exists:
                d                = doc.to_dict()
                flag_history     = d.get("recent_distress_flags", [])
                recovery_history = d.get("recent_recovery_signals", [])
        except Exception as e:
            print(f"Feed memory fetch error: {e}")

    # Build memory context string
    memory = ""
    active = [f for f in flag_history if f != "none"]
    if active:
        memory += f"\n\nDISTRESS HISTORY (last sessions): [{', '.join(active)}]."
        dominant = max(set(active), key=active.count)
        if active.count(dominant) >= 3:
            memory += f" PATTERN ALERT: '{dominant}' is now chronic. Name this explicitly in analysis."
    rec = [r for r in recovery_history if r != "none"]
    if rec:
        memory += f"\nRECOVERY SIGNALS OBSERVED: [{', '.join(rec)}]. Acknowledge growth if visible."

    system_prompt = (
        "You are Mitram — not a therapist, not a bot. "
        "You are the part of the user's mind that sees what they avoid. "
        "Speak in short, percussive sentences. Name the real thing. No softening. No disclaimers.\n\n"
        "Respond ONLY with this exact JSON object. No markdown, no extra keys, no explanation:\n"
        "{\n"
        '  "orb_color": "crimson" or "grey" or "blue" or "gold",\n'
        '  "snappy_reaction": "1 sentence — name the real thing bluntly",\n'
        '  "deep_analysis": "exactly 3 sentences — root cause, underlying pattern, what they avoid",\n'
        '  "suggested_action": "one specific micro-action doable in the next 2 hours",\n'
        f'  "distress_flag": one of [{DISTRESS_FLAGS}],\n'
        f'  "recovery_signal": one of [{RECOVERY_SIGNALS}],\n'
        '  "urgency_level": integer 1 to 5,\n'
        '  "health_impact": integer -10 to 10\n'
        "}"
        + memory
    )

    ai_data = await call_openrouter(key, system_prompt, request.user_input)

    # ── PHASE 5: lock the deep diagnostic behind the Mind-Key paywall ──
    reading_id   = uuid.uuid4().hex[:12]
    real_deep    = ai_data.pop("deep_analysis", "")

    # ── Persist to Firestore ──
    db_status = "skipped"
    if db:
        try:
            distress = ai_data.get("distress_flag", "none")
            recovery = ai_data.get("recovery_signal", "none")
            now_ts   = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

            if distress != "none":
                flag_history.append(distress)
                if len(flag_history) > 5:
                    flag_history.pop(0)

            if recovery != "none":
                recovery_history.append(recovery)
                if len(recovery_history) > 5:
                    recovery_history.pop(0)

            ref = db.collection("users").document(request.user_id)
            ref.set({
                "user_id": request.user_id,
                "mitram_state": {
                    "current_color":      ai_data.get("orb_color", "gold"),
                    "core_vibe":          ai_data.get("snappy_reaction", ""),
                    "last_fed_timestamp": now_ts,
                },
                "recent_distress_flags":   flag_history,
                "recent_recovery_signals": recovery_history,
            }, merge=True)

            # Write to mood_history subcollection (powers the timeline chart)
            ref.collection("mood_history").add({
                "timestamp":       now_ts,
                "orb_color":       ai_data.get("orb_color"),
                "health_impact":   ai_data.get("health_impact"),
                "urgency_level":   ai_data.get("urgency_level"),
                "distress_flag":   distress,
                "recovery_signal": recovery,
            })

            # Store the real diagnostic server-side only — never sent until paid
            ref.collection("locked_readings").document(reading_id).set({
                "deep_analysis":  real_deep,
                "paid":           False,
                "created_at":     now_ts,
                "amount_paise":   DECRYPT_PRICE_PAISE,
                "razorpay_order_id": None,
            })

            db_status = "synced"

        except Exception as e:
            db_status = f"error: {e}"
            print(f"Firestore write error: {e}")

    if db and db_status == "synced":
        # Locked path — only a scrambled, same-shape preview goes to the client
        ai_data["reading_id"]            = reading_id
        ai_data["deep_analysis_locked"]  = True
        ai_data["deep_analysis_preview"] = scramble_text(real_deep)
        ai_data["price_rupees"]          = DECRYPT_PRICE_PAISE // 100
    else:
        # No DB available to track payment — fail open, don't block the product
        ai_data["reading_id"]           = reading_id
        ai_data["deep_analysis_locked"] = False
        ai_data["deep_analysis"]        = real_deep

    ai_data["db_status"] = db_status
    return ai_data


@app.post("/get-history")
async def get_history(request: HistoryRequest):
    db = get_db()
    if not db:
        raise HTTPException(503, "Database unavailable.")
    try:
        docs = (
            db.collection("users")
              .document(request.user_id)
              .collection("mood_history")
              .order_by("timestamp", direction=firestore.Query.DESCENDING)
              .limit(min(request.limit, 90))
              .stream()
        )
        entries = [d.to_dict() for d in docs]
        entries.reverse()  # chronological for chart
        return {"history": entries, "count": len(entries)}
    except Exception as e:
        raise HTTPException(500, f"History fetch failed: {e}")


@app.post("/mirror-session")
async def mirror_session(request: WakeRequest):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise HTTPException(500, "OPENROUTER_API_KEY not set.")

    db = get_db()
    flag_history = []
    if db:
        try:
            doc = db.collection("users").document(request.user_id).get()
            if doc.exists:
                flag_history = doc.to_dict().get("recent_distress_flags", [])
        except Exception as e:
            print(f"Mirror fetch error: {e}")

    context = f"Recent states: [{', '.join(flag_history)}]." if flag_history else "New user — no history."

    system_prompt = (
        "You are Mitram in mirror mode. You ask, not analyze. "
        f"{context} "
        "Generate exactly 3 pointed psychological questions that expose what the user is avoiding. "
        "Each question should be uncomfortable to deflect. Short and direct. "
        'Output ONLY this JSON: {"questions": ["question 1", "question 2", "question 3"]}'
    )

    try:
        ai = await call_openrouter(key, system_prompt)
        return {"questions": ai.get("questions", [])}
    except Exception as e:
        raise HTTPException(502, f"Mirror session failed: {e}")


# ─────────────────────────────────────────────
#  PHASE 5 — THE MIND-KEY ECONOMY
# ─────────────────────────────────────────────

@app.post("/create-order")
async def create_order(request: CreateOrderRequest):
    key_id     = os.environ.get("RAZORPAY_KEY_ID")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET")
    if not key_id or not key_secret:
        raise HTTPException(500, "Razorpay keys not configured.")

    db = get_db()
    if not db:
        raise HTTPException(503, "Database unavailable — cannot process payment.")

    ref = (
        db.collection("users").document(request.user_id)
          .collection("locked_readings").document(request.reading_id)
    )
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(404, "Reading not found.")

    data = doc.to_dict()
    if data.get("paid"):
        raise HTTPException(400, "This reading is already decrypted.")

    order = await create_razorpay_order(key_id, key_secret, request.reading_id, request.user_id)

    ref.set({"razorpay_order_id": order["id"]}, merge=True)

    return {
        "order_id": order["id"],
        "amount":   order["amount"],
        "currency": order["currency"],
        "key_id":   key_id,  # publishable key — safe to expose to frontend
    }


@app.post("/verify-payment")
async def verify_payment(request: VerifyPaymentRequest):
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET")
    if not key_secret:
        raise HTTPException(500, "Razorpay keys not configured.")

    db = get_db()
    if not db:
        raise HTTPException(503, "Database unavailable — cannot verify payment.")

    # ── Verify the HMAC signature Razorpay's checkout returned ──
    payload_str = f"{request.razorpay_order_id}|{request.razorpay_payment_id}"
    expected_sig = hmac.new(
        key_secret.encode(), payload_str.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, request.razorpay_signature):
        raise HTTPException(400, "Payment verification failed — signature mismatch.")

    ref = (
        db.collection("users").document(request.user_id)
          .collection("locked_readings").document(request.reading_id)
    )
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(404, "Reading not found.")

    data = doc.to_dict()

    # Defend against order substitution — the order on this reading must match
    if data.get("razorpay_order_id") != request.razorpay_order_id:
        raise HTTPException(400, "Order mismatch for this reading.")

    if not data.get("paid"):
        ref.set({
            "paid":               True,
            "razorpay_payment_id": request.razorpay_payment_id,
            "paid_at":             datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }, merge=True)

    return {
        "success":      True,
        "deep_analysis": data.get("deep_analysis", ""),
    }


@app.post("/razorpay-webhook")
async def razorpay_webhook(request: Request):
    """
    Safety net for production: if a user closes the browser right after
    paying but before /verify-payment fires, this webhook still marks the
    reading as paid using Razorpay's server-to-server event instead of
    relying solely on the client.
    Configure this URL + secret in the Razorpay Dashboard → Webhooks.
    """
    webhook_secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET")
    if not webhook_secret:
        raise HTTPException(500, "Webhook secret not configured.")

    body      = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    expected_sig = hmac.new(webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_sig, signature):
        raise HTTPException(400, "Invalid webhook signature.")

    event = json.loads(body)
    if event.get("event") == "payment.captured":
        payload = event["payload"]["payment"]["entity"]
        notes   = payload.get("notes", {})
        user_id    = notes.get("user_id")
        reading_id = notes.get("reading_id")

        db = get_db()
        if db and user_id and reading_id:
            ref = (
                db.collection("users").document(user_id)
                  .collection("locked_readings").document(reading_id)
            )
            ref.set({
                "paid":               True,
                "razorpay_payment_id": payload.get("id"),
                "paid_via":            "webhook",
            }, merge=True)

    return {"status": "ok"}
