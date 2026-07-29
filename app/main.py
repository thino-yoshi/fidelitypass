from contextlib import asynccontextmanager
import time
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.limiter import limiter
from app.routers import auth, merchants, cards, scan, notifications, users, rewards
from app.routers.notifications import send_due_notifications
from app.logger import get_logger

logger = get_logger("api")

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(send_due_notifications, "interval", minutes=1, id="notif_scheduler")
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(title="FidelityPass API", version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = round((time.time() - start) * 1000)
    logger.info(f"{request.method} {request.url.path} → {response.status_code} ({duration}ms)")
    return response

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(merchants.router, prefix="/merchants", tags=["Merchants"])
app.include_router(cards.router, prefix="/cards", tags=["Cards"])
app.include_router(scan.router, prefix="/scan", tags=["Scan"])
app.include_router(notifications.router, prefix="/notifications", tags=["Notifications"])
app.include_router(users.router, prefix="/users", tags=["Users"])
app.include_router(rewards.router, prefix="/rewards", tags=["Rewards"])

@app.get("/")
def root():
    return {"message": "FidelityPass API is running !"}
