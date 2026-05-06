from fastapi import FastAPI

from app.core.config import SERVICE_NAME

app = FastAPI(title="SentryGate")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE_NAME}
