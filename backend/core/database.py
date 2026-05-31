# core/database.py — Supabase client factory for Paper Peeler
#
# Provides two Supabase clients:
#   get_service_client() → service role, bypasses RLS (used by peeler_repository in supabase mode)
#   get_anon_client()    → anon key, respects RLS
#
# Radar has its own async client in radar/core/database.py.

from typing import Optional
from supabase import create_client, Client

from config import SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_KEY

_service_client: Optional[Client] = None
_anon_client: Optional[Client] = None


def get_service_client() -> Client:
    global _service_client
    if _service_client is None:
        if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env")
        _service_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    return _service_client


def get_anon_client() -> Client:
    global _anon_client
    if _anon_client is None:
        if not SUPABASE_URL or not SUPABASE_ANON_KEY:
            raise ValueError("SUPABASE_URL and SUPABASE_ANON_KEY must be set in .env")
        _anon_client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    return _anon_client


async def test_connection() -> bool:
    try:
        db = get_service_client()
        db.table("peels").select("id").limit(1).execute()
        return True
    except Exception as e:
        print(f"  ❌ Database connection failed: {e}")
        return False
