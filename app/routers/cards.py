from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.database import supabase, SECRET_KEY
from jose import jwt, JWTError
import uuid
import csv
import io
from datetime import datetime, timedelta, timezone

router = APIRouter(tags=["Cards"])
security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=["HS256"])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Token invalide")

class CreateCardRequest(BaseModel):
    merchant_id: str

class JoinMerchantRequest(BaseModel):
    static_qr_token: str

@router.post("/join")
def join_via_static_qr(data: JoinMerchantRequest, user=Depends(get_current_user)):
    if user["user_type"] != "client":
        raise HTTPException(status_code=403, detail="Réservé aux clients")

    merchant_res = supabase.table("merchants")\
        .select("id, business_name, category, stamps_required, reward_description")\
        .eq("static_qr_token", data.static_qr_token)\
        .execute()
    if not merchant_res.data:
        raise HTTPException(status_code=404, detail="QR code invalide")

    merchant = merchant_res.data[0]
    merchant_id = merchant["id"]

    existing = supabase.table("loyalty_cards")\
        .select("*")\
        .eq("client_id", user["sub"])\
        .eq("merchant_id", merchant_id)\
        .execute()

    if existing.data:
        return {"already_member": True, "card": existing.data[0], "merchant": merchant}

    qr_token = str(uuid.uuid4())
    card = supabase.table("loyalty_cards").insert({
        "client_id": user["sub"],
        "merchant_id": merchant_id,
        "stamps_count": 0,
        "qr_token": qr_token,
    }).execute()

    return {"already_member": False, "card": card.data[0], "merchant": merchant}

@router.post("/")
def create_card(data: CreateCardRequest, user=Depends(get_current_user)):
    client_id = user["sub"]
    existing = supabase.table("loyalty_cards").select("id").eq("client_id", client_id).eq("merchant_id", data.merchant_id).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Carte déjà existante pour ce commerce")
    qr_token = str(uuid.uuid4())
    card = supabase.table("loyalty_cards").insert({
        "client_id": client_id,
        "merchant_id": data.merchant_id,
        "stamps_count": 0,
        "qr_token": qr_token
    }).execute()
    return card.data[0]

@router.get("/me")
def get_my_cards(user=Depends(get_current_user), limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    client_id = user["sub"]
    cards = supabase.table("loyalty_cards").select(
        "*, merchants(business_name, category, stamps_required, reward_description)"
    ).eq("client_id", client_id).range(offset, offset + limit - 1).execute()
    return cards.data if cards.data else []

@router.get("/qr/{card_id}")
def get_dynamic_qr(card_id: str, user=Depends(get_current_user)):
    # Vérifier que la carte appartient bien à ce client
    card = supabase.table("loyalty_cards").select("*").eq("id", card_id).eq("client_id", user["sub"]).execute()
    if not card.data:
        raise HTTPException(status_code=404, detail="Carte non trouvée")
    
    # Générer un token JWT qui expire dans 60s
    payload = {
        "qr_token": card.data[0]["qr_token"],
        "card_id": card_id,
        "exp": datetime.utcnow() + timedelta(seconds=60)
    }
    dynamic_token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")

    return {"dynamic_token": dynamic_token, "expires_in": 60}

@router.get("/my-history")
def get_client_history(user=Depends(get_current_user)):
    if user["user_type"] != "client":
        raise HTTPException(status_code=403, detail="Réservé aux clients")

    res = supabase.table("scan_history")\
        .select("*")\
        .eq("client_id", user["sub"])\
        .order("scanned_at", desc=True)\
        .limit(100)\
        .execute()

    results = []
    for scan in res.data:
        merchant_res = supabase.table("merchants")\
            .select("business_name, category")\
            .eq("id", scan["merchant_id"])\
            .execute()
        merchant = merchant_res.data[0] if merchant_res.data else {}
        scan["merchant"] = merchant
        results.append(scan)

    return results


@router.get("/scan-history")
def get_scan_history(user=Depends(get_current_user)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    res = supabase.table("scan_history")\
        .select("*")\
        .eq("merchant_id", user["sub"])\
        .order("scanned_at", desc=True)\
        .limit(50)\
        .execute()

    results = []
    for scan in res.data:
        client_res = supabase.table("users")\
            .select("name, email")\
            .eq("id", scan["client_id"])\
            .execute()
        client = client_res.data[0] if client_res.data else {}
        scan["client"] = client
        results.append(scan)

    return results

@router.get("/clients")
def get_merchant_clients(user=Depends(get_current_user), limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    cards_res = supabase.table("loyalty_cards")\
        .select("*")\
        .eq("merchant_id", user["sub"])\
        .range(offset, offset + limit - 1)\
        .execute()

    results = []
    for card in cards_res.data:
        client_res = supabase.table("users")\
            .select("name, email, profile_picture_url")\
            .eq("id", card["client_id"])\
            .execute()
        client = client_res.data[0] if client_res.data else {}
        card["client"] = client
        results.append(card)

    return results


class AdjustStampRequest(BaseModel):
    delta: int  # +1 ou -1


@router.post("/{card_id}/adjust-stamp")
def adjust_stamp(card_id: str, data: AdjustStampRequest, user=Depends(get_current_user)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    if data.delta not in (1, -1):
        raise HTTPException(status_code=400, detail="delta doit être 1 ou -1")

    card_res = supabase.table("loyalty_cards")\
        .select("*")\
        .eq("id", card_id)\
        .eq("merchant_id", user["sub"])\
        .execute()
    if not card_res.data:
        raise HTTPException(status_code=404, detail="Carte non trouvée")

    card = card_res.data[0]
    merchant_res = supabase.table("merchants").select("stamps_required").eq("id", user["sub"]).execute()
    stamps_required = merchant_res.data[0]["stamps_required"] if merchant_res.data else 10

    new_count = max(0, min(card["stamps_count"] + data.delta, stamps_required))
    reward_reached = new_count >= stamps_required
    if reward_reached:
        new_count = 0

    supabase.table("loyalty_cards").update({"stamps_count": new_count}).eq("id", card_id).execute()

    supabase.table("scan_history").insert({
        "merchant_id": user["sub"],
        "client_id": card["client_id"],
        "card_id": card_id,
        "stamps_count": new_count,
        "reward_reached": reward_reached,
        "manual": True,
    }).execute()

    return {
        "success": True,
        "stamps_count": new_count,
        "stamps_required": stamps_required,
        "reward_reached": reward_reached,
    }


@router.get("/export-csv")
def export_clients_csv(user=Depends(get_current_user)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    merchant_res = supabase.table("merchants").select("stamps_required").eq("id", user["sub"]).execute()
    stamps_required = merchant_res.data[0]["stamps_required"] if merchant_res.data else 10

    cards_res = supabase.table("loyalty_cards").select("*").eq("merchant_id", user["sub"]).execute()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Nom", "Email", "Tampons", "Tampons requis", "Tampons restants", "Date inscription"])

    for card in cards_res.data:
        client_res = supabase.table("users").select("name, email").eq("id", card["client_id"]).execute()
        client = client_res.data[0] if client_res.data else {}
        stamps = card["stamps_count"]
        created = card.get("created_at", "")[:10] if card.get("created_at") else ""
        writer.writerow([
            client.get("name", ""),
            client.get("email", ""),
            stamps,
            stamps_required,
            max(0, stamps_required - stamps),
            created,
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=clients.csv"},
    )


@router.get("/stats/daily")
def get_daily_stats(user=Depends(get_current_user)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    since = (datetime.now(timezone.utc) - timedelta(days=29)).isoformat()
    res = supabase.table("scan_history")\
        .select("scanned_at, reward_reached")\
        .eq("merchant_id", user["sub"])\
        .gte("scanned_at", since)\
        .execute()

    daily = {}
    for scan in res.data:
        day = scan["scanned_at"][:10]
        if day not in daily:
            daily[day] = {"scans": 0, "rewards": 0}
        daily[day]["scans"] += 1
        if scan.get("reward_reached"):
            daily[day]["rewards"] += 1

    result = []
    for i in range(30):
        day = (datetime.now(timezone.utc) - timedelta(days=29 - i)).strftime("%Y-%m-%d")
        d = daily.get(day, {"scans": 0, "rewards": 0})
        result.append({"date": day, "scans": d["scans"], "rewards": d["rewards"]})

    return result


@router.get("/stats")
def get_merchant_stats(user=Depends(get_current_user)):
    if user["user_type"] != "merchant":
        raise HTTPException(status_code=403, detail="Réservé aux commerçants")

    cards_res = supabase.table("loyalty_cards")\
        .select("*")\
        .eq("merchant_id", user["sub"])\
        .execute()

    cards = cards_res.data
    total_clients = len(cards)
    total_stamps = sum(c["stamps_count"] for c in cards)

    rewards_res = supabase.table("scan_history")\
        .select("id")\
        .eq("merchant_id", user["sub"])\
        .eq("reward_reached", True)\
        .execute()
    total_rewards = len(rewards_res.data)

    scans_res = supabase.table("scan_history")\
        .select("id")\
        .eq("merchant_id", user["sub"])\
        .execute()
    total_scans = len(scans_res.data)

    return {
        "total_clients": total_clients,
        "total_stamps": total_stamps,
        "total_rewards": total_rewards,
        "total_scans": total_scans,
    }