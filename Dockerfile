# 1. Use the official lightweight Python 3.11 image to minimize cold start times
FROM python:3.11-slim

# 2. Force Python to immediately print logs to Cloud Run (crucial for debugging)
ENV PYTHONUNBUFFERED=True

# 3. Set the directory inside the container where your app will live
WORKDIR /app

# 4. Copy your requirements file first to cache the dependencies
COPY requirements.txt .

# 5. Install the Python packages
RUN pip install --no-cache-dir -r requirements.txt

# 6. Copy your FastAPI logic (main.py) into the container
COPY . .

# 7. Start the FastAPI server using Uvicorn, binding it to port 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
