import os
import psycopg2
import psycopg2.extras
from psycopg2.extras import Json
from contextlib import contextmanager
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

# ── Auth Supabase (JWT uniquement — plus de requêtes DB via Supabase) ──────────
SUPABASE_URL         = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
SUPABASE_JWT_SECRET  = os.getenv("SUPABASE_JWT_SECRET")
SECRET_KEY           = os.getenv("SECRET_KEY")

# Client Supabase gardé UNIQUEMENT pour Auth (get_user fallback) et Storage (avatars)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# ── Neon PostgreSQL (toutes les requêtes DB) ───────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL")


@contextmanager
def _get_conn():
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=15)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class _Result:
    """Émule la réponse Supabase : .data contient une liste de dicts."""
    def __init__(self, rows):
        self.data = [dict(r) for r in rows] if rows else []


def _adapt(v):
    """Convertit dict/list en Json psycopg2 pour les colonnes JSONB."""
    if isinstance(v, (dict, list)):
        return Json(v)
    return v


class _Query:
    """Builder de requête qui émule l'API supabase-py pour les opérations CRUD."""

    def __init__(self, table: str):
        self._table     = table
        self._cols      = "*"
        self._conds     = []      # liste de (col, op, val)
        self._in_conds  = []      # liste de (col, [vals])
        self._is_conds  = []      # liste de (col, "null"|"not null")
        self._order_col = None
        self._order_desc = False
        self._limit_val  = None
        self._range_from = None
        self._range_to   = None
        self._data       = None   # pour insert/update/upsert
        self._conflict   = None   # pour upsert

    # ── SELECT ────────────────────────────────────────────────────────────────
    def select(self, cols: str = "*"):
        self._cols = cols
        return self

    def eq(self, col: str, val):
        self._conds.append((col, "=", val))
        return self

    def neq(self, col: str, val):
        self._conds.append((col, "!=", val))
        return self

    def in_(self, col: str, vals: list):
        self._in_conds.append((col, vals))
        return self

    def is_(self, col: str, val: str):
        """val: "null" ou "not null"."""
        self._is_conds.append((col, val))
        return self

    def lte(self, col: str, val):
        self._conds.append((col, "<=", val))
        return self

    def gte(self, col: str, val):
        self._conds.append((col, ">=", val))
        return self

    def order(self, col: str, desc: bool = False):
        self._order_col  = col
        self._order_desc = desc
        return self

    def limit(self, n: int):
        self._limit_val = n
        return self

    def range(self, start: int, end: int):
        self._range_from = start
        self._range_to   = end
        return self

    def _where_clause(self, params: list):
        parts = []
        for col, op, val in self._conds:
            parts.append(f"{col} {op} %s")
            params.append(val)
        for col, vals in self._in_conds:
            if not vals:
                parts.append("FALSE")
            else:
                placeholders = ",".join(["%s"] * len(vals))
                parts.append(f"{col} IN ({placeholders})")
                params.extend(vals)
        for col, val in self._is_conds:
            if val == "null":
                parts.append(f"{col} IS NULL")
            else:
                parts.append(f"{col} IS NOT NULL")
        return ("WHERE " + " AND ".join(parts)) if parts else ""

    def execute(self) -> _Result:
        if self._data is not None and self._conflict is not None:
            return self._run_upsert()
        if self._data is not None and hasattr(self, '_update_mode') and self._update_mode:
            return self._run_update()
        if self._data is not None:
            return self._run_insert()
        return self._run_select()

    def _run_select(self) -> _Result:
        params: list = []
        where = self._where_clause(params)

        # Transformer les colonnes style Supabase ("*, merchants(...)") en SQL
        cols = self._cols
        if "(" in cols:
            cols = self._expand_cols(cols)

        sql = f"SELECT {cols} FROM {self._table} {where}"
        if self._order_col:
            sql += f" ORDER BY {self._order_col} {'DESC' if self._order_desc else 'ASC'}"
        if self._range_from is not None:
            sql += f" LIMIT {self._range_to - self._range_from + 1} OFFSET {self._range_from}"
        elif self._limit_val is not None:
            sql += f" LIMIT {self._limit_val}"

        with _get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return _Result(cur.fetchall())

    def _expand_cols(self, cols: str) -> str:
        """Transforme "*, merchants(a, b)" en "*, merchants.a, merchants.b"
        pour les JOIN implicites — version simplifiée (les routers font des JOIN manuels)."""
        import re
        # Ex: "*, merchants(business_name, category, stamps_required, ...)"
        # → retourner juste "*" et laisser les routers gérer les joins
        return re.sub(r'\w+\([^)]+\)', '', cols).strip().rstrip(',').strip() or "*"

    def _run_insert(self) -> _Result:
        if isinstance(self._data, list):
            rows = self._data
        else:
            rows = [self._data]
        if not rows:
            return _Result([])

        keys = list(rows[0].keys())
        cols_str = ", ".join(keys)
        vals_str = ", ".join([f"({', '.join(['%s'] * len(keys))})"] * len(rows))
        params   = [_adapt(row[k]) for row in rows for k in keys]
        sql = f"INSERT INTO {self._table} ({cols_str}) VALUES {vals_str} RETURNING *"

        print(f"[DB_DEBUG] TABLE={self._table} KEYS={keys} PARAMS_COUNT={len(params)}", flush=True)
        if self._table == "users":
            safe = [(str(p)[:20] if i % len(keys) != 1 else "***") for i, p in enumerate(params)]
            print(f"[DB_DEBUG] PARAMS_SAFE={safe}", flush=True)

        with _get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows_out = cur.fetchall()
                if self._table == "users":
                    print(f"[DB_DEBUG] RESULT_KEYS={list(rows_out[0].keys()) if rows_out else 'empty'}", flush=True)
                    print(f"[DB_DEBUG] RESULT_EMAIL={rows_out[0].get('email') if rows_out else 'N/A'}", flush=True)
                return _Result(rows_out)

    def _run_update(self) -> _Result:
        params: list = []
        set_parts = [f"{k} = %s" for k in self._data.keys()]
        params.extend(_adapt(v) for v in self._data.values())
        where = self._where_clause(params)
        sql = f"UPDATE {self._table} SET {', '.join(set_parts)} {where} RETURNING *"

        with _get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return _Result(cur.fetchall())

    def _run_upsert(self) -> _Result:
        row  = self._data if isinstance(self._data, dict) else self._data[0]
        keys = list(row.keys())
        cols_str    = ", ".join(keys)
        vals_str    = ", ".join(["%s"] * len(keys))
        params      = [_adapt(row[k]) for k in keys]
        conflict_col = self._conflict
        update_parts = ", ".join([f"{k} = EXCLUDED.{k}" for k in keys if k != conflict_col])
        sql = (f"INSERT INTO {self._table} ({cols_str}) VALUES ({vals_str}) "
               f"ON CONFLICT ({conflict_col}) DO UPDATE SET {update_parts} RETURNING *")

        with _get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return _Result(cur.fetchall())

    # ── INSERT ────────────────────────────────────────────────────────────────
    def insert(self, data):
        self._data = data
        self._update_mode = False
        return self

    # ── UPDATE ────────────────────────────────────────────────────────────────
    def update(self, data: dict):
        self._data = data
        self._update_mode = True
        return self

    # ── UPSERT ────────────────────────────────────────────────────────────────
    def upsert(self, data, on_conflict: str = "id"):
        self._data     = data
        self._conflict = on_conflict
        return self

    # ── DELETE ────────────────────────────────────────────────────────────────
    def delete(self):
        self._update_mode = None
        self._data = _Sentinel()
        return self

    def _execute_delete(self) -> _Result:
        params: list = []
        where = self._where_clause(params)
        sql = f"DELETE FROM {self._table} {where} RETURNING *"
        with _get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return _Result(cur.fetchall())


class _Sentinel:
    """Marqueur interne pour distinguer delete() d'insert()/update()."""
    pass


# Patch pour que delete().eq().execute() fonctionne
_original_execute = _Query.execute

def _patched_execute(self) -> _Result:
    if isinstance(self._data, _Sentinel):
        return self._execute_delete()
    return _original_execute(self)

_Query.execute = _patched_execute


class _DB:
    """Point d'entrée global : db.table("nom").select(...).execute()"""
    def table(self, name: str) -> _Query:
        return _Query(name)

    def execute_sql(self, query: str, params=None) -> _Result:
        """SQL brut pour les requêtes complexes (JOIN, etc.)."""
        with _get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, params or [])
                try:
                    return _Result(cur.fetchall())
                except psycopg2.ProgrammingError:
                    return _Result([])


db = _DB()
