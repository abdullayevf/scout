from fastapi import FastAPI

from apps.api.router_admin import router as admin_router

app = FastAPI(title="Scout API", version="0.0.1")
app.include_router(admin_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
