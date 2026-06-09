# orb-engine-core

🧠 Neura-Mitram Core Backend Engine

This repository houses the lightweight, high-performance, serverless backend engine for Neura-Mitram (Your Neural Friend). 

The application utilizes FastAPI to handle incoming asynchronous traffic and communicates natively with Google Gemini 1.5 Flash using the modern `google-genai` SDK. It is designed to run in a stateless, containerized sandbox on **Google Cloud Run**, automatically scaling down to zero when idle to achieve 100% cost efficiency.

---

🏗️ Technical Architecture

* **API Framework:** FastAPI (Asynchronous Python Web Framework)
* **AI Model Engine:** Gemini 1.5 Flash
* **Deployment System:** Docker container hosted on Google Cloud Run
* **Database Sync:** Firebase Firestore

---

📂 Repository File Matrix

* `main.py` - Core routing logic, API endpoint declarations, and system prompts for the Gemini model.
* `requirements.txt` - Python module dependencies mapping runtime packages (`fastapi`, `google-genai`, `uvicorn`, `pydantic`).
* `Dockerfile` - The step-by-step build recipe utilized by Google Cloud Build to compile the runtime Linux sandbox.

---

📡 Exposed API Endpoint

 `POST /feed-mitram`
Receives raw user statements or data strings, passes them through a tailored psychological processing pipeline, and returns structured JSON instructions to morph the PWA frontend orb.

 Request Body Payload Format:
```json
{
  "user_id": "google_uid_string",
  "user_input": "I keep dreaming about falling from a tall building and catching myself at the last second."
}
