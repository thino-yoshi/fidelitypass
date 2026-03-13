from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.dependencies import get_current_user
from app.database import supabase

router = APIRouter(tags=["Users"])

class FCMTokenUpdate(BaseModel):
    fcm_token: str

@router.put("/fcm-token")
def update_fcm_token(data: FCMTokenUpdate, user=Depends(get_current_user)):
    res = supabase.table("users")\
        .update({"fcm_token": data.fcm_token})\
        .eq("id", user["sub"])\
        .execute()
    return {"message": "Token FCM mis à jour"}