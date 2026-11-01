import os
from fastapi import FastAPI
from dotenv import load

load_dotenv()

app = FastAPI(title="Voice Transcription Daemon & API", version="1.0.0")

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "Voice Transcription Backend running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8100)
