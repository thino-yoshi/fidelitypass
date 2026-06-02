from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from app.dependencies import get_current_user
from app.database import supabase
import bcrypt
import time

router = APIRouter(tags=["Users"])

class FCMTokenUpdate(BaseModel):
    fcm_token: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class DeleteAccountRequest(BaseModel):
    password: str

class UpdateProfileRequest(BaseModel):
    name: str | None = None
    email: str | None = None

@router.put("/fcm-token")
def update_fcm_token(data: FCMTokenUpdate, user=Depends(get_current_user)):
    # Upsert : crée la ligne si elle n'existe pas encore (nouveaux users Supabase Auth)
    supabase.table("users").upsert(
        {
            "id":        user["sub"],
            "email":     user.get("email", ""),
            "user_type": user.get("user_type", "client"),
            "fcm_token": data.fcm_token,
        },
        on_conflict="id",
    ).execute()
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


# NOTE: The Supabase Storage bucket "avatars" must exist and be set to PUBLIC
#       before this endpoint will work. Create it in the Supabase dashboard:
#       Storage → New bucket → name: "avatars" → toggle Public on.
#
# NOTE: The "users" table must have a column:  profile_picture_url TEXT
#       Run in Supabase SQL editor:
#       ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_picture_url TEXT;

@router.post("/profile-picture")
async def upload_profile_picture(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user)
):
    """Upload a profile picture — stores in Supabase Storage bucket 'avatars'."""
    user_id = current_user["sub"]
    contents = await file.read()
    content_type = file.content_type or "image/jpeg"
    ext = "png" if content_type == "image/png" else "jpg"
    filename = f"{user_id}.{ext}"

    # Supprimer l'ancien fichier s'il existe (ignore erreur si absent)
    try:
        supabase.storage.from_("avatars").remove([filename])
    except Exception:
        pass

    # Upload du nouveau fichier
    try:
        supabase.storage.from_("avatars").upload(
            path=filename,
            file=contents,
            file_options={"content-type": content_type, "cache-control": "3600", "upsert": "true"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur storage upload: {str(e)}")

    # URL publique avec cache-buster
    raw_url = supabase.storage.from_("avatars").get_public_url(filename)
    public_url = f"{raw_url}?v={int(time.time())}"

    # Mise à jour en base
    db_res = supabase.table("users").update(
        {"profile_picture_url": public_url}
    ).eq("id", user_id).execute()

    if not db_res.data:
        raise HTTPException(
            status_code=500,
            detail=f"Fichier uploadé mais update DB échoué (user_id={user_id})"
        )

    return {"profile_picture_url": public_url}


@router.get("/me")
async def get_me(current_user=Depends(get_current_user)):
    """Get the current user's profile, including profile_picture_url and is_google."""
    user_id = current_user["sub"]
    try:
        result = supabase.table("users").select("id, name, email, role, profile_picture_url, password_hash").eq("id", user_id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur base de données: {str(e)}")

    if not result.data:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")

    user = result.data[0]
    user["is_google"] = user.pop("password_hash", "") == "google_oauth"
    return user

@router.patch("/me")
async def update_profile(data: UpdateProfileRequest, current_user=Depends(get_current_user)):
    """Modifier nom et/ou email — interdit pour les comptes Google."""
    user_id = current_user["sub"]

    # Vérifier que ce n'est pas un compte Google
    check = supabase.table("users").select("password_hash").eq("id", user_id).execute()
    if check.data and check.data[0].get("password_hash") == "google_oauth":
        raise HTTPException(status_code=403, detail="Impossible de modifier un compte Google")

    updates = {}
    if data.name:  updates["name"]  = data.name.strip()
    if data.email: updates["email"] = data.email.strip().lower()
    if not updates:
        raise HTTPException(status_code=400, detail="Aucune donnée à mettre à jour")

    res = supabase.table("users").update(updates).eq("id", user_id).execute()
    if not res.data:
        raise HTTPException(status_code=500, detail="Erreur mise à jour")
    return {"message": "Profil mis à jour", **updates}