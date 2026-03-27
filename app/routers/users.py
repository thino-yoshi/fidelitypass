from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.dependencies import get_current_user
from app.database import supabase
import bcrypt

router = APIRouter(tags=["Users"])

class FCMTokenUpdate(BaseModel):
    fcm_token: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class DeleteAccountRequest(BaseModel):
    password: str

@router.put("/fcm-token")
def update_fcm_token(data: FCMTokenUpdate, user=Depends(get_current_user)):
    supabase.table("users")\
        .update({"fcm_token": data.fcm_token})\
        .eq("id", user["sub"])\
        .execute()
    return {"message": "Token FCM mis à jour"}

@router.put("/change-password")
def change_password(data: ChangePasswordRequest, user=Depends(get_current_user)):
    user_res = supabase.table("users").select("password_hash").eq("id", user["sub"]).execute()
    if not user_res.data:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")

    stored_hash = user_res.data[0]["password_hash"]
    if stored_hash == "google_oauth":
        raise HTTPException(status_code=400, detail="Compte Google — mot de passe non modifiable")

    if not bcrypt.checkpw(data.current_password.encode(), stored_hash.encode()):
        raise HTTPException(status_code=401, detail="Mot de passe actuel incorrect")

    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="Le nouveau mot de passe doit faire au moins 6 caractères")

    new_hash = bcrypt.hashpw(data.new_password.encode(), bcrypt.gensalt()).decode()
    supabase.table("users").update({"password_hash": new_hash}).eq("id", user["sub"]).execute()
    return {"message": "Mot de passe mis à jour"}

@router.delete("/account")
def delete_account(data: DeleteAccountRequest, user=Depends(get_current_user)):
    user_res = supabase.table("users").select("password_hash").eq("id", user["sub"]).execute()
    if not user_res.data:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")

    stored_hash = user_res.data[0]["password_hash"]
    if stored_hash != "google_oauth":
        if not bcrypt.checkpw(data.password.encode(), stored_hash.encode()):
            raise HTTPException(status_code=401, detail="Mot de passe incorrect")

    # Supprimer les données liées
    cards_res = supabase.table("loyalty_cards").select("id").eq("client_id", user["sub"]).execute()
    card_ids = [c["id"] for c in cards_res.data]
    for card_id in card_ids:
        supabase.table("scan_history").delete().eq("card_id", card_id).execute()
    supabase.table("loyalty_cards").delete().eq("client_id", user["sub"]).execute()
    supabase.table("users").delete().eq("id", user["sub"]).execute()

    return {"message": "Compte supprimé"}