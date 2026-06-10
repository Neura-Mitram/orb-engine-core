import os
import json
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai
from google.genai import types
import firebase_admin
from firebase_admin import firestore

app = FastAPI(title="Neura-Mitram Core Engine")

# Security: Broadened temporarily to ensure your Cloudflare domain connects cleanly during debugging
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Database NATIVELY
db = None
try:
    firebase_admin.initialize_app()
    db = firestore.client()
    print("✓ Firestore Native Client initialized successfully.")
except Exception as e:
    print(f"✗ Critical Firebase Init Error: {str(e)}")

# Initialize AI Client
client = None
try:
    client = genai.Client()
    print("✓ Gemini client initialized successfully.")
except Exception as e:
    print(f"✗ Critical Gemini Init Error: {str(e)}")

class FeedRequest(BaseModel):
    user_id: str
    user_input: str

@app.get("/")
def health_check():
    return {
        "status": "online", 
        "service": "Neura-Mitram Debug Mode",
        "database_bound": db is not None,
        "gemini_bound": client is not None
    }

@app.post("/feed-mitram")
async def feed_mitram(request: FeedRequest):
    # Verify client states immediately before running code
    if not client:
        raise HTTPException(status_code=500, detail="Gemini client is offline or missing GEMINI_API_KEY environment variable.")

    try:
        system_prompt = (
            "You are Neura-Mitram, a sentient, psychological digital entity serving as a mirror "
            "to the user's subconscious. Analyze their input and return a precise JSON response."
        )

        response_schema = {
            "type": "OBJECT",
            "properties": {
                "orb_color": {"type": "STRING", "description": "Must be: 'crimson', 'grey', 'blue', or 'gold'."},
                "snappy_reaction": {"type": "STRING", "description": "A 1-sentence witty psychological reaction."},
                "deep_analysis": {"type": "STRING", "description": "A profound 3-sentence root-cause analysis."},
                "distress_flag": {"type": "STRING", "description": "Must be: 'none', 'insomnia', 'relationship_toxicity', 'burnout', 'general_anxiety'."},
                "health_impact": {"type": "INTEGER", "description": "Integer between -10 and 10."}
            },
            "required": ["orb_color", "snappy_reaction", "deep_analysis", "distress_flag", "health_impact"]
        }

        # Request response from Gemini
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=request.user_input,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    response_schema=response_schema,
                    temperature=0.7
                )
            )
            ai_data = json.loads(response.text)
        except Exception as ai_err:
            raise HTTPException(status_code=502, detail=f"Gemini API Processing Failed: {str(ai_err)}")
        
        # Log to Firestore with explicit internal error handling
        db_status = "Not executed"
        if db is not None:
            try:
                user_ref = db.collection("users").document(request.user_id)
                user_doc = user_ref.get()
                flag_history = []
                
                if user_doc.exists:
                    existing_data = user_doc.to_dict()
                    flag_history = existing_data.get("recent_distress_flags", [])
                    
                if ai_data["distress_flag"] != "none":
                    flag_history.append(ai_data["distress_flag"])
                    if len(flag_history) > 5:
                        flag_history.pop(0)

                user_ref.set({
                    "user_id": request.user_id,
                    "mitram_state": {
                        "current_color": ai_data["orb_color"],
                        "core_vibe": ai_data["snappy_reaction"],
                        "last_fed_timestamp": datetime.utcnow().isoformat() + "Z"
                    },
                    "recent_distress_flags": flag_history
                }, merge=True)
                db_status = "✓ Sync successful"
            except Exception as db_err:
                db_status = f"✗ Firestore operational failure: {str(db_err)}"
                print(f"Firestore Write Error: {str(db_err)}")
        else:
            db_status = "✗ Firestore skipped: Client initialization failed at startup."

        # Append the database debug status directly to the response payload
        ai_data["db_status"] = db_status
        return ai_data

    except HTTPException as http_err:
        raise http_err
    except Exception as general_err:
        raise HTTPException(status_code=500, detail=f"Internal Core Server Exception: {str(general_err)}")
