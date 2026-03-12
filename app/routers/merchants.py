from fastapi import APIRouter, HTTPException
from app.database import supabase

router = APIRouter()

@router.get("/")
def get_merchants():
    result = supabase.table("merchants").select(
        "*, users(name, email)"
    ).execute()
    
    if not result.data:
        return []
    
    merchants = []
    for m in result.data:
        merchants.append({
            "id": m["id"],
            "business_name": m["business_name"],
            "category": m["category"],
            "stamps_required": m["stamps_required"],
            "reward_description": m["reward_description"]
        })
    
    return merchants

@router.get("/{merchant_id}")
def get_merchant(merchant_id: str):
    result = supabase.table("merchants").select("*").eq("id", merchant_id).execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Commerce introuvable")
    
    return result.data[0]