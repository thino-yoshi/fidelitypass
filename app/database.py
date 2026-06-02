import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL        = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
SUPABASE_JWT_SECRET  = os.getenv("SUPABASE_JWT_SECRET")   # pour vérifier les tokens Supabase Auth
SECRET_KEY           = os.getenv("SECRET_KEY")             # pour les QR codes dynamiques internes

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)