from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy import text

from app.auth import CurrentUser, get_current_user
from app.config import settings
from app.db import SessionDep
from app.routers import me, meetings, participants

app = FastAPI(
    title="Meetings API",
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

api = APIRouter(prefix="/api")


@api.get("/health", tags=["health"])
async def health(session: SessionDep) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"status": "ok"}


# Everything but /api/health needs a signed-in user; meetings are scoped to their owner.
api.include_router(me.router)
api.include_router(meetings.router)
api.include_router(participants.router, dependencies=[Depends(get_current_user)])


@api.post("/ai/parse", tags=["ai"])
async def local_parse_agenda(
    payload: dict,
    user: CurrentUser,
) -> dict:
    import json

    from fastapi import HTTPException

    from app.ai.agenda_lambda import handler

    event = {
        "headers": {"authorization": f"Bearer mock-user-{user.id}"},
        "body": json.dumps(payload),
    }
    res = handler(event)
    body = json.loads(res["body"])
    if res["statusCode"] != 200:
        raise HTTPException(status_code=res["statusCode"], detail=body.get("error", "Parse failed"))
    return body


app.include_router(api)


@app.get("/", include_in_schema=False)
@app.get("/api", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/api/docs")
