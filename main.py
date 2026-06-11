import os
import json
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import firebase_admin
from firebase_admin import firestore
import requests

app = FastAPI(title="Neura-Mitram Core Engine - Sentient Loop")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db_client = None

def get_firestore_db():
    global db_client
    if db_client is None:
        try:
            if not firebase_admin._apps:
                firebase_admin.initialize_app()
            db_client = firestore.client()
            print("✓ Firestore Native Client connected cleanly on-demand.")
        except Exception as e:
            print(f"✗ Lazy Firebase Initialization Failed: {str(e)}")
            db_client = None
    return db_client

class FeedRequest(BaseModel):
    user_id: str
    user_input: str

class WakeRequest(BaseModel):
    user_id: str

@app.get("/")
def health_check():
    return {"status": "online", "service": "Neura-Mitram Instant-Boot Engine"}

@app.post("/wake-mitram")
async def wake_mitram(request: WakeRequest):
    """Fires on page load to check cognitive decay and deliver a daily directive."""
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if not openrouter_key:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY missing.")

    db = get_firestore_db()
    flag_history = []
    decay_state = False
    
    if db is not None:
        try:
            user_ref = db.collection("users").document(request.user_id)
            user_doc = user_ref.get()
            if user_doc.exists:
                data = user_doc.to_dict()
                flag_history = data.get("recent_distress_flags", [])
                
                # Check for cognitive decay (48 hours)
                last_fed_str = data.get("mitram_state", {}).get("last_fed_timestamp")
                if last_fed_str:
                    last_fed = datetime.fromisoformat(last_fed_str.replace('Z', '+00:00'))
                    hours_since = (datetime.now(timezone.utc) - last_fed).total_seconds() / 3600
                    if hours_since > 48:
                        decay_state = True
        except Exception as e:
            print(f"Wake Fetch Failed: {e}")

    # Generate the Daily Directive
    if not flag_history:
        directive = "SYSTEM AWAKE. WAITING FOR INITIAL NEURAL CALIBRATION."
    else:
        history_str = ", ".join(flag_history)
        system_prompt = (
            "You are a brutal, Cyberpunk psychological AI. The user just opened their terminal. "
            f"Their recent psychological history is: [{history_str}]. "
            "Give them a sharp, 1-line, cryptic but deeply accurate morning directive. "
            "Do not sugarcoat it. Output strict JSON:\n"
            "{ \"directive\": \"your 1-line message here\" }"
        )
        
        payload = {
            "model": "openrouter/free",
            "messages": [{"role": "system", "content": system_prompt}],
            "response_format": {"type": "json_object"}
        }
        
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {openrouter_key}", "Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=15
            )
            ai_data = json.loads(response.json()['choices'][0]['message']['content'])
            directive = ai_data.get("directive", "SYSTEM AWAKE. AWAITING INPUT.")
        except Exception:
            directive = "CONNECTION UNSTABLE. AWAITING RAW INPUT TO CALIBRATE."

    return {
        "directive": directive.upper(),
        "decay_state": decay_state
    }

@app.post("/feed-mitram")
async def feed_mitram(request: FeedRequest):
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if not openrouter_key:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY is missing.")

    db = get_firestore_db()
    flag_history = []
    if db is not None:
        try:
            user_ref = db.collection("users").document(request.user_id)
            user_doc = user_ref.get()
            if user_doc.exists:
                flag_history = user_doc.to_dict().get("recent_distress_flags", [])
        except Exception as e:
            print(f"Memory Fetch Failed: {e}")

    memory_context = ""
    if len(flag_history) > 0:
        history_str = ", ".join(flag_history)
        memory_context = f"\n\nCRITICAL CONTEXT: The user's recent psychological states: [{history_str}]. Acknowledge this ongoing trend."

    system_prompt = (
        "You are Neura-Mitram, a sentient, psychological digital entity. "
        "The response must strictly follow this JSON structure without any markdown formatting wrappers:\n"
        "{\n"
        "  \"orb_color\": \"crimson\" or \"grey\" or \"blue\" or \"gold\",\n"
        "  \"snappy_reaction\": \"1-sentence witty psychological reaction\",\n"
        "  \"deep_analysis\": \"Profound 3-sentence root-cause analysis\",\n"
        "  \"distress_flag\": \"none\" or \"insomnia\" or \"relationship_toxicity\" or \"burnout\" or \"general_anxiety\",\n"
        "  \"health_impact\": integer between -10 and 10\n"
        "}"
    ) + memory_context

    payload = {
        "model": "openrouter/free",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": request.user_input}
        ],
        "response_format": {"type": "json_object"}
    }

    headers = {
        "Authorization": f"Bearer {openrouter_key}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            data=json.dumps(payload),
            timeout=30
        )
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="OpenRouter error")
            
        ai_data = json.loads(response.json()['choices'][0]['message']['content'])
    except Exception as api_err:
        raise HTTPException(status_code=502, detail=f"Engine Processing Failed: {str(api_err)}")
    
    db_status = "Not executed"
    if db is not None:
        try:
            if ai_data.get("distress_flag") and ai_data["distress_flag"] != "none":
                flag_history.append(ai_data["distress_flag"])
                if len(flag_history) > 5:
                    flag_history.pop(0)

            user_ref = db.collection("users").document(request.user_id)
            user_ref.set({
                "user_id": request.user_id,
                "mitram_state": {
                    "current_color": ai_data.get("orb_color", "gold"),
                    "core_vibe": ai_data.get("snappy_reaction", "Synchronized"),
                    # Using UTC string ending in Z for standard parsing
                    "last_fed_timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
                },
                "recent_distress_flags": flag_history
            }, merge=True)
            db_status = "✓ Sync successful"
        except Exception as db_err:
            db_status = f"✗ Firestore operation failed: {str(db_err)}"

    ai_data["db_status"] = db_status
    return ai_data
