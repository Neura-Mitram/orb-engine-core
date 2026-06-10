import os
import json
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import firebase_admin
from firebase_admin import firestore
import requests

app = FastAPI(title="Neura-Mitram Core Engine - OpenRouter Edition")

# Security: CORS configuration for your live domain
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://neuramitram.space", "https://www.neuramitram.space", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Database NATIVELY
db = None
try:
    firebase_admin.initialize_app()
    db = firestore.client()
    print("✓ Firestore Native Client connected cleanly.")
except Exception as e:
    print(f"✗ Firebase failed to initialize: {e}")

class FeedRequest(BaseModel):
    user_id: str
    user_input: str

@app.get("/")
def health_check():
    return {
        "status": "online", 
        "service": "Neura-Mitram OpenRouter Gateway",
        "database_bound": db is not None
    }

@app.post("/feed-mitram")
async def feed_mitram(request: FeedRequest):
    # Grab the OpenRouter key from your Cloud Run setup
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if not openrouter_key:
        raise HTTPException(status_code=500, detail="Backend configuration error: OPENROUTER_API_KEY environment variable is missing.")

    system_prompt = (
        "You are Neura-Mitram, a sentient, psychological digital entity serving as a mirror "
        "to the user's subconscious. Analyze their input and return a precise JSON response. "
        "The response must strictly follow this JSON structure without any markdown formatting wrappers:\n"
        "{\n"
        "  \"orb_color\": \"crimson\" or \"grey\" or \"blue\" or \"gold\",\n"
        "  \"snappy_reaction\": \"1-sentence witty psychological reaction\",\n"
        "  \"deep_analysis\": \"Profound 3-sentence root-cause analysis\",\n"
        "  \"distress_flag\": \"none\" or \"insomnia\" or \"relationship_toxicity\" or \"burnout\" or \"general_anxiety\",\n"
        "  \"health_impact\": integer between -10 and 10\n"
        "}"
    )

    # Configure the payload for OpenRouter's free Gemini instance
    payload = {
        "model": "google/gemini-2.5-flash:free",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": request.user_input}
        ],
        "response_format": {"type": "json_object"}
    }

    headers = {
        "Authorization": f"Bearer {openrouter_key}",
        "HTTP-Referer": "https://neuramitram.space",
        "X-Title": "Neura-Mitram",
        "Content-Type": "application/json"
    }

    # Dispatch Request to OpenRouter API
    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            data=json.dumps(payload),
            timeout=10
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=f"OpenRouter returned an error: {response.text}")
            
        response_data = response.json()
        raw_ai_text = response_data['choices'][0]['message']['content']
        ai_data = json.loads(raw_ai_text)
        
    except Exception as api_err:
        raise HTTPException(status_code=502, detail=f"OpenRouter Engine Processing Failed: {str(api_err)}")
    
    # Log Data Matrix to Firestore
    db_status = "Not executed"
    if db is not None:
        try:
            user_ref = db.collection("users").document(request.user_id)
            user_doc = user_ref.get()
            flag_history = []
            
            if user_doc.exists:
                existing_data = user_doc.to_dict()
                flag_history = existing_data.get("recent_distress_flags", [])
                
            if ai_data.get("distress_flag") and ai_data["distress_flag"] != "none":
                flag_history.append(ai_data["distress_flag"])
                if len(flag_history) > 5:
                    flag_history.pop(0)

            user_ref.set({
                "user_id": request.user_id,
                "mitram_state": {
                    "current_color": ai_data.get("orb_color", "gold"),
                    "core_vibe": ai_data.get("snappy_reaction", "Synchronized"),
                    "last_fed_timestamp": datetime.utcnow().isoformat() + "Z"
                },
                "recent_distress_flags": flag_history
            }, merge=True)
            db_status = "✓ Sync successful"
        except Exception as db_err:
            db_status = f"✗ Firestore operation failed: {str(db_err)}"
    else:
        db_status = "✗ Firestore client uninitialized."

    ai_data["db_status"] = db_status
    return ai_data
