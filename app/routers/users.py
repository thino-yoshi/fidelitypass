from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from app.dependencies import get_current_user
from app.database import supabase, db
import bcrypt
import time
import os
import boto3

_r2 = boto3.client(
    "s3",
    endpoint_url=os.getenv("R2_ENDPOINT"),
    aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
    region_name="auto",
)
_R2_BUCKET     = os.getenv("R2_BUCKET", "qarta-storage")
_R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "")

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
    db.table("users").update({"fcm_token": data.fcm_token}).eq("id", user["sub"]).execute()
    return {"message": "Token FCM mis à jour"}

@router.put("/change-password")
def change_password(data: ChangePasswordRequest, user=Depends(get_current_user)):
    user_res = db.table("users").select("password_hash").eq("id", user["sub"]).execute()
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
    db.table("users").update({"password_hash": new_hash}).eq("id", user["sub"]).execute()
    return {"message": "Mot de passe mis à jour"}

@router.delete("/account")
def delete_account(data: DeleteAccountRequest, user=Depends(get_current_user)):
    user_res = db.table("users").select("password_hash").eq("id", user["sub"]).execute()
    if not user_res.data:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")

    stored_hash = user_res.data[0]["password_hash"]
    if stored_hash != "google_oauth":
        if not bcrypt.checkpw(data.password.encode(), stored_hash.encode()):
            raise HTTPException(status_code=401, detail="Mot de passe incorrect")

    # ON DELETE CASCADE gère la suppression des données liées
    db.table("users").delete().eq("id", user["sub"]).execute()

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
    """Upload a profile picture — stores in Cloudflare R2 bucket 'qarta-storage'."""
    user_id = current_user["sub"]
    contents = await file.read()
    content_type = file.content_type or "image/jpeg"
    ext = "png" if content_type == "image/png" else "jpg"
    key = f"avatars/{user_id}.{ext}"

    try:
        _r2.put_object(
            Bucket=_R2_BUCKET,
            Key=key,
            Body=contents,
            ContentType=content_type,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur storage upload: {str(e)}")

    public_url = f"{_R2_PUBLIC_URL}/{key}?v={int(time.time())}"

    db_res = db.table("users").update(
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
        result = db.table("users").select("id, name, email, profile_picture_url, password_hash").eq("id", user_id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur base de données: {str(e)}")

    if not result.data:
        # Première connexion OAuth (Google/Apple) : créer l'utilisateur dans Neon
        email = current_user.get("email") or ""
        name = email.split("@")[0] if email else "Utilisateur"
        try:
            new = db.table("users").insert({
                "id": user_id,
                "email": email,
                "name": name,
                "user_type": current_user.get("user_type", "client"),
                "password_hash": "SUPABASE_AUTH",
            }).execute()
            result_data = new.data[0] if new.data else {"id": user_id, "email": email, "name": name, "profile_picture_url": None}
        except Exception:
            raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
        user = result_data
        user.pop("password_hash", None)
        user["is_google"] = False
        user["is_oauth"]  = True
        return user

    user = result.data[0]
    ph = user.pop("password_hash", "") or ""
    user["is_google"] = ph == "google_oauth"
    user["is_oauth"]  = ph in ("google_oauth", "SUPABASE_AUTH")
    return user

@router.patch("/me")
async def update_profile(data: UpdateProfileRequest, current_user=Depends(get_current_user)):
    """Modifier nom et/ou email. L'email est interdit pour les comptes Google et Apple."""
    user_id = current_user["sub"]

    check = db.table("users").select("password_hash").eq("id", user_id).execute()
    password_hash = check.data[0].get("password_hash") if check.data else None
    is_oauth = password_hash in ("google_oauth", "SUPABASE_AUTH")

    updates = {}
    if data.name:
        updates["name"] = data.name.strip()
    if data.email:
        if is_oauth:
            raise HTTPException(status_code=403, detail="Impossible de modifier l'email d'un compte Google ou Apple")
        updates["email"] = data.email.strip().lower()
    if not updates:
        raise HTTPException(status_code=400, detail="Aucune donnée à mettre à jour")

    res = db.table("users").update(updates).eq("id", user_id).execute()
    if not res.data:
        raise HTTPException(status_code=500, detail="Erreur mise à jour")
    return {"message": "Profil mis à jour", **updates}