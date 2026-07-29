from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel
from app.database import supabase, SECRET_KEY
from jose import jwt, JWTError
import uuid
import csv
import io
import os
import json as json_lib
import time
import hashlib
import zipfile
import base64
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
    if user.get("user_type", "client") != "client":
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
        "*, merchants(business_name, category, stamps_required, reward_description, program_type, points_per_euro, points_required)"
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
    if user.get("user_type", "client") != "client":
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


# ══════════════════════════════════════════════════════════════════════════════
# WALLET — Google Wallet (Android) + Apple Wallet (iOS)
# ══════════════════════════════════════════════════════════════════════════════

# 1×1 transparent PNG utilisé comme icône placeholder pour le .pkpass
_ICON_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


def _hex_to_rgb(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return "rgb(26, 26, 46)"
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgb({r}, {g}, {b})"


def _card_primary_color(merchant: dict) -> str:
    try:
        design = json_lib.loads(merchant.get("card_design") or "{}")
        colors = design.get("bgColors", [])
        hex_c = colors[0] if colors else "#1a1a2e"
        return hex_c if hex_c.startswith("#") else f"#{hex_c}"
    except Exception:
        return "#1a1a2e"


def _gw_sign_jwt(payload: dict, private_key_pem: str) -> str:
    """Signe un JWT Google Wallet avec RS256 via la lib cryptography."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding

    header = {"alg": "RS256", "typ": "JWT"}
    h_enc = base64.urlsafe_b64encode(
        json_lib.dumps(header, separators=(",", ":")).encode()
    ).rstrip(b"=").decode()
    p_enc = base64.urlsafe_b64encode(
        json_lib.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    ).rstrip(b"=").decode()
    msg = f"{h_enc}.{p_enc}"
    key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    sig = key.sign(msg.encode(), asym_padding.PKCS1v15(), hashes.SHA256())
    return f"{msg}.{base64.urlsafe_b64encode(sig).rstrip(b'=').decode()}"


# ── 1. Google Wallet JWT ───────────────────────────────────────────────────────

@router.get("/{card_id}/wallet/google")
def get_google_wallet_jwt(card_id: str, user=Depends(get_current_user)):
    """Retourne un JWT signé à passer à pay.google.com/gp/v/save/{jwt}."""
    issuer_id   = os.getenv("GW_ISSUER_ID", "")
    sa_email    = os.getenv("GW_SA_EMAIL", "")
    private_key = os.getenv("GW_PRIVATE_KEY", "").replace("\\n", "\n")

    if not issuer_id or not sa_email or not private_key:
        raise HTTPException(
            status_code=503,
            detail="Google Wallet non configuré — ajoutez GW_ISSUER_ID, GW_SA_EMAIL, GW_PRIVATE_KEY dans Railway"
        )

    card_res = supabase.table("loyalty_cards")\
        .select("*, merchants(business_name, stamps_required, points_required, reward_description, program_type, card_design)")\
        .eq("id", card_id).eq("client_id", user["sub"]).execute()
    if not card_res.data:
        raise HTTPException(status_code=404, detail="Carte non trouvée")

    card     = card_res.data[0]
    merchant = card["merchants"]
    is_points = merchant.get("program_type") == "points"
    count    = (card.get("points_count") if is_points else card.get("stamps_count")) or 0
    goal     = (merchant.get("points_required") if is_points else merchant.get("stamps_required")) or 10
    hex_color = _card_primary_color(merchant)

    mk = card["merchant_id"].replace("-", "")
    ck = card_id.replace("-", "")
    class_id  = f"{issuer_id}.m{mk}"
    object_id = f"{issuer_id}.c{ck}"

    loyalty_class = {
        "id": class_id,
        "issuerName": "Qarta",
        "programName": merchant["business_name"],
        "rewardsTierLabel": "Fidélité",
        "hexBackgroundColor": hex_color,
        "countryCode": "BE",
        "reviewStatus": "UNDER_REVIEW",
    }
    loyalty_object = {
        "id": object_id,
        "classId": class_id,
        "state": "ACTIVE",
        "accountId": user["sub"],
        "accountName": user.get("name", "Client"),
        "loyaltyPoints": {
            "balance": {"string": f"{count}/{goal}"},
            "label": "Points" if is_points else "Tampons",
        },
        "textModulesData": [{
            "header": "Récompense",
            "body": merchant.get("reward_description", ""),
            "id": "reward",
        }],
        "barcode": {"type": "QR_CODE", "value": card["qr_token"], "alternateText": ""},
        "hexBackgroundColor": hex_color,
    }

    gw_payload = {
        "iss": sa_email,
        "aud": "google",
        "typ": "savetowallet",
        "iat": int(time.time()),
        "payload": {"loyaltyClasses": [loyalty_class], "loyaltyObjects": [loyalty_object]},
        "origins": [os.getenv("API_BASE_URL", "https://fidelitypass-production.up.railway.app")],
    }

    token = _gw_sign_jwt(gw_payload, private_key)
    return {"jwt": token, "save_url": f"https://pay.google.com/gp/v/save/{token}"}


# ── 2. Apple Wallet — URL signée (appelée par le client Flutter avec auth) ────

@router.get("/{card_id}/wallet/apple-url")
def get_apple_wallet_url(card_id: str, user=Depends(get_current_user)):
    """Génère une URL .pkpass temporaire (5 min) pour iOS Safari."""
    card_res = supabase.table("loyalty_cards").select("id")\
        .eq("id", card_id).eq("client_id", user["sub"]).execute()
    if not card_res.data:
        raise HTTPException(status_code=404, detail="Carte non trouvée")

    token = jwt.encode({
        "card_id": card_id,
        "client_id": user["sub"],
        "exp": datetime.utcnow() + timedelta(minutes=5),
    }, SECRET_KEY, algorithm="HS256")

    base = os.getenv("API_BASE_URL", "https://fidelitypass-production.up.railway.app")
    return {"url": f"{base}/cards/{card_id}/wallet/apple?t={token}"}


# ── 3. Apple Wallet — génère le .pkpass (accès par token temporaire) ──────────

@router.get("/{card_id}/wallet/apple")
def get_apple_wallet_pass(card_id: str, t: str = Query(...)):
    """Retourne le fichier .pkpass pour iOS (signé si certificat configuré)."""
    try:
        payload = jwt.decode(t, SECRET_KEY, algorithms=["HS256"])
        if payload.get("card_id") != card_id:
            raise ValueError("card_id mismatch")
        client_id = payload["client_id"]
    except Exception:
        raise HTTPException(status_code=401, detail="Token invalide ou expiré")

    card_res = supabase.table("loyalty_cards")\
        .select("*, merchants(business_name, stamps_required, points_required, reward_description, program_type, card_design)")\
        .eq("id", card_id).eq("client_id", client_id).execute()
    if not card_res.data:
        raise HTTPException(status_code=404, detail="Carte non trouvée")

    card     = card_res.data[0]
    merchant = card["merchants"]
    is_points = merchant.get("program_type") == "points"
    count    = (card.get("points_count") if is_points else card.get("stamps_count")) or 0
    goal     = (merchant.get("points_required") if is_points else merchant.get("stamps_required")) or 10
    hex_color = _card_primary_color(merchant)

    pass_type_id = os.getenv("AW_PASS_TYPE_ID", "pass.com.qarta.loyalty")
    team_id      = os.getenv("AW_TEAM_ID", "XXXXXXXXXX")

    pass_dict = {
        "formatVersion": 1,
        "passTypeIdentifier": pass_type_id,
        "serialNumber": card_id,
        "teamIdentifier": team_id,
        "organizationName": "Qarta",
        "description": f"Carte fidélité {merchant['business_name']}",
        "logoText": merchant["business_name"],
        "backgroundColor": _hex_to_rgb(hex_color),
        "foregroundColor": "rgb(255, 255, 255)",
        "labelColor": "rgb(180, 180, 200)",
        "storeCard": {
            "primaryFields": [{
                "key": "balance",
                "label": "Points" if is_points else "Tampons",
                "value": f"{count}/{goal}",
            }],
            "auxiliaryFields": [{
                "key": "reward",
                "label": "Récompense",
                "value": merchant.get("reward_description", ""),
            }],
        },
        "barcodes": [{
            "message": card["qr_token"],
            "format": "PKBarcodeFormatQR",
            "messageEncoding": "iso-8859-1",
        }],
    }

    pass_bytes = json_lib.dumps(pass_dict, ensure_ascii=False, indent=2).encode("utf-8")

    files: dict[str, bytes] = {
        "pass.json":  pass_bytes,
        "icon.png":   _ICON_PNG,
        "icon@2x.png": _ICON_PNG,
    }
    manifest = {name: hashlib.sha1(data).hexdigest() for name, data in files.items()}
    manifest_bytes = json_lib.dumps(manifest).encode("utf-8")
    files["manifest.json"] = manifest_bytes

    # Signature (optionnel — nécessite AW_CERT_PEM + AW_KEY_PEM + AW_WWDR_PEM dans Railway)
    cert_pem = os.getenv("AW_CERT_PEM", "").replace("\\n", "\n")
    key_pem  = os.getenv("AW_KEY_PEM",  "").replace("\\n", "\n")
    wwdr_pem = os.getenv("AW_WWDR_PEM", "").replace("\\n", "\n")

    if cert_pem and key_pem:
        try:
            from cryptography.hazmat.primitives import serialization, hashes as cr_hashes
            from cryptography import x509
            from cryptography.hazmat.primitives.serialization import pkcs7 as pkcs7_ser

            cert = x509.load_pem_x509_certificate(cert_pem.encode())
            key  = serialization.load_pem_private_key(key_pem.encode(), password=None)
            builder = pkcs7_ser.PKCS7SignatureBuilder()\
                .set_data(manifest_bytes)\
                .add_signer(cert, key, cr_hashes.SHA256())
            if wwdr_pem:
                builder = builder.add_certificate(
                    x509.load_pem_x509_certificate(wwdr_pem.encode())
                )
            files["signature"] = builder.sign(
                serialization.Encoding.DER,
                [pkcs7_ser.PKCS7Options.DetachedSignature],
            )
        except Exception:
            pass  # Pass sans signature → iOS refusera l'installation mais utile en dev

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)

    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.apple.pkpass",
        headers={"Content-Disposition": f"attachment; filename=qarta_{card_id[:8]}.pkpass"},
    )


@router.delete("/{card_id}")
def delete_card(card_id: str, user=Depends(get_current_user)):
    """Supprime une carte de fidélité appartenant au client connecté."""
    if user.get("user_type") != "client":
        raise HTTPException(status_code=403, detail="Réservé aux clients")

    # Vérifier que la carte appartient bien à ce client
    card_res = supabase.table("loyalty_cards")\
        .select("id")\
        .eq("id", card_id)\
        .eq("client_id", user["sub"])\
        .execute()

    if not card_res.data:
        raise HTTPException(status_code=404, detail="Carte non trouvée")

    # Supprimer l'historique de scan lié
    supabase.table("scan_history").delete().eq("card_id", card_id).execute()

    # Supprimer la carte
    supabase.table("loyalty_cards").delete().eq("id", card_id).execute()

    return {"message": "Carte supprimée"}