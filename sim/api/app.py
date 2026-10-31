from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sim.api.routes import router

app = FastAPI(title="AgentSimCity", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


def main() -> None:
    import uvicorn

    uvicorn.run("sim.api.app:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()
