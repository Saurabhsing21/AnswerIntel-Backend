from fastapi import FastAPI

from app.api.router import router as api_router


app = FastAPI(title="AnswerIntel API")

app.include_router(api_router)


@app.get("/health")
def health_check():
    return {"status": "ok"}