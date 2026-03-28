from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.routers import auth, merchants, cards, scan, notifications, users
from app.routers.notifications import send_due_notifications

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(send_due_notifications, "interval", minutes=1, id="notif_scheduler")
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(title="FidelityPass API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(merchants.router, prefix="/merchants", tags=["Merchants"])
app.include_router(cards.router, prefix="/cards", tags=["Cards"])
app.include_router(scan.router, prefix="/scan", tags=["Scan"])
app.include_router(notifications.router, prefix="/notifications", tags=["Notifications"])
app.include_router(users.router, prefix="/users", tags=["Users"])

@app.get("/")
def root():
    return {"message": "FidelityPass API is running !"}
