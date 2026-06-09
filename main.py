import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai
from google.genai import types
import json

# Initialize FastAPI App
app = FastAPI(title="Neura-Mitram Core Engine")

# Security: Allow the frontend (Cloudflare Pages) to communicate with the backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, replace "*" with "https://neuramitram.com"
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize the 2026 Google GenAI Client
# This automatically picks up the GEMINI_API_KEY from your Cloud Run environment variables
try:
    client = genai.Client()
except Exception as e:
    print(f"Failed to initialize GenAI client. Ensure GEMINI_API_KEY is set. Error: {e}")

# Define the expected format of the incoming request from the frontend
class FeedRequest(BaseModel):
    user_id: str
    user_input: str

# Health Check Route to verify the server is awake
@app.get("/")
def health_check():
    return {"status": "online", "service": "Neura-Mitram Core"}

# The Main Processing Engine
@app.post("/feed-mitram")
async def feed_mitram(request: FeedRequest):
    try:
        # The Persona & Logic Instructions
        system_prompt = (
            "You are Neura-Mitram, a sentient, psychological digital entity serving as a mirror "
            "to the user's subconscious. The user is feeding you raw thoughts, worries, or texts. "
            "You must analyze their input and return a precise JSON response."
        )

        # Define the strict JSON schema we want the AI to output
        response_schema = {
            "type": "OBJECT",
            "properties": {
                "orb_color": {
                    "type": "STRING",
                    "description": "Must be exactly one of: 'crimson' (anxious), 'grey' (burned out), 'blue' (calm), 'gold' (balanced)."
                },
                "snappy_reaction": {
                    "type": "STRING",
                    "description": "A 1-sentence, witty, engaging psychological mirror response to their input."
                },
                "deep_analysis": {
                    "type": "STRING",
                    "description": "A profound, 3-sentence root-cause analysis of their mental state."
                },
                "distress_flag": {
                    "type": "STRING",
                    "description": "Must be exactly one of: 'none', 'insomnia', 'relationship_toxicity', 'burnout', 'general_anxiety'."
                },
                "health_impact": {
                    "type": "INTEGER",
                    "description": "An integer between -10 and 10 representing the mental health impact of their input."
                }
            },
            "required": ["orb_color", "snappy_reaction", "deep_analysis", "distress_flag", "health_impact"]
        }

        # Make the high-speed call to Gemini 2.5 Flash
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=request.user_input,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=response_schema,
                temperature=0.7 # 0.7 gives a good balance of creativity and structure
            )
        )
        
        # Parse the AI's string response into an actual JSON dictionary
        json_data = json.loads(response.text)
        
        # Return the payload securely to the Cloudflare frontend
        return json_data

    except Exception as e:
        # If anything fails, throw a clean 500 error back to the frontend
        raise HTTPException(status_code=500, detail=str(e))
