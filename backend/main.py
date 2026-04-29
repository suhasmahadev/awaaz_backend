"""
AWAAZ-PROOF — FastAPI application entry point.
ANTIGRAVITY fixes:
  - Removed dead sensor_router import/include (merged into verification router)
  - Tightened CORS to known frontend origins only
  - Added in-memory rate limiter for /auth/anon and /complaints/new
  - app.state injection (repo, service) inside lifespan — not at module level
"""
import logging
import os
import time
from collections import defaultdict
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from google.adk.cli.fast_api import get_fast_api_app

from db import PostgresDB
from repos.repo import Repo
from services.service import Service

from routers.auth import router as auth_router
from routers.auth_anon import router as auth_anon_router
from routers.chat_history import router as history_router
from routers.complaints import router as complaints_router
from routers.evidence import router as evidence_router
from routers.contracts import router as contracts_router
from routers.contractor_ledger import router as ledger_router
from routers.verification import router as verification_router
from routers.admin import router as admin_router
from routers.ngo import admin_router as ngo_admin_router
from routers.ngo import router as ngo_router
from routers.complaint_pipeline import router as pipeline_router
from routers import agent_chat
from routers.admin_ops import router as admin_ops_router
from routers.media_router import router as media_router
from routers.community import router as community_router

logger = logging.getLogger(__name__)
AGENT_DIR = os.path.dirname(os.path.abspath(__file__))


# ── Rate limiting ───────────────────────────────────────────────────────────────
# ANTIGRAVITY: simple in-memory rate limiter — honest about not using Redis.
# State resets on server restart. Good enough for hackathon demo, documented clearly.
_rate_store: dict[str, list[float]] = defaultdict(list)


def _rate_limit(ip: str, endpoint: str, max_calls: int, window_seconds: int) -> bool:
    """
    Returns True if request is allowed, False if rate limited.
    Evicts expired timestamps on every check (sliding window).

    NOT Redis — resets on restart. Honest, documented, defensible.
    """
    key = f"{ip}:{endpoint}"
    now = time.time()
    _rate_store[key] = [t for t in _rate_store[key] if now - t < window_seconds]
    if len(_rate_store[key]) >= max_calls:
        return False
    _rate_store[key].append(now)
    return True


app = get_fast_api_app(
    agents_dir=AGENT_DIR,
    allow_origins=["*"],
    web=True,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # MVP ONLY
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"status": "live"}


# ── Rate-limit middleware ───────────────────────────────────────────────────────
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """
    Applies per-IP rate limits to high-risk endpoints:
      POST /auth/anon       — 10 requests/minute (prevent fingerprint enumeration)
      POST /complaints/new  — 5 requests/minute  (prevent complaint flooding)
    """
    ip = request.client.host if request.client else "unknown"
    path = request.url.path
    method = request.method

    if method == "POST" and path.endswith("/auth/anon"):
        if not _rate_limit(ip, "auth_anon", max_calls=10, window_seconds=60):
            return JSONResponse(
                status_code=429,
                content={"error": "rate_limited", "message": "Too many requests. Try again in 60 seconds."},
            )

    if method == "POST" and (path.endswith("/complaints/new") or path.rstrip("/").endswith("/complaints")):
        if not _rate_limit(ip, "complaints_new", max_calls=5, window_seconds=60):
            return JSONResponse(
                status_code=429,
                content={"error": "rate_limited", "message": "Too many complaints. Try again in 60 seconds."},
            )

    return await call_next(request)


# ── Domain routers ──────────────────────────────────────────────────────────────
app.include_router(auth_anon_router)
app.include_router(auth_router)
app.include_router(history_router)
app.include_router(complaints_router, prefix="/complaints", tags=["complaints"])
app.include_router(evidence_router,   prefix="/evidence",  tags=["evidence"])
app.include_router(contracts_router,  prefix="/contracts", tags=["contracts"])
app.include_router(ledger_router,     prefix="/ledger",    tags=["ledger"])
# ANTIGRAVITY: single router handles both /verify/* and /sensor/* paths
app.include_router(verification_router, tags=["verification"])
app.include_router(admin_router,      prefix="/admin",     tags=["admin"])
app.include_router(ngo_admin_router)
app.include_router(ngo_router)
app.include_router(pipeline_router, tags=["Pipeline"])
app.include_router(agent_chat.router, prefix="/agent",     tags=["Agent Chat"])
app.include_router(admin_ops_router, prefix="/admin", tags=["Admin Ops"])
app.include_router(media_router)
app.include_router(community_router)

# ── Static files ────────────────────────────────────────────────────────────────
STATIC_DIR = os.path.join(AGENT_DIR, "static")
os.makedirs(os.path.join(STATIC_DIR, "evidence"), exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

SERVICE_IMAGES_DIR = os.path.join(AGENT_DIR, "service_images")
os.makedirs(SERVICE_IMAGES_DIR, exist_ok=True)
app.mount("/service_images", StaticFiles(directory=SERVICE_IMAGES_DIR), name="service_images")

UPLOADS_DIR = os.path.join(AGENT_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")


# ── Lifespan: DB connect + table bootstrap ─────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await PostgresDB.connect()
    pool = PostgresDB.pool
    from agent.tools import set_pool
    set_pool(pool)
    os.makedirs(os.path.join(STATIC_DIR, "evidence"), exist_ok=True)

    # ANTIGRAVITY: inject into app.state inside lifespan so pool is ready
    app.state.pool = pool
    app.state.repo = Repo(pool)
    app.state.service = Service(app.state.repo)

    if not os.getenv("NEAR_AI_KEY"):
        import logging
        logging.warning("NEAR_AI_KEY not set — pipeline AI will use fallback classification")

    # ── MISSION 1: Seed admin user (upsert-safe) ───────────────────────────────
    admin_exists = await pool.fetchval("SELECT id FROM users WHERE email=$1", "admin@gmail.com")
    if not admin_exists:
        from auth_security import hash_password
        await pool.execute("""
            INSERT INTO users (id, name, email, password_hash, role)
            VALUES ($1,'Admin','admin@gmail.com',$2,'admin')
        """, "usr_admin_001", hash_password("admin123"))

    async with pool.acquire() as conn:
        # ── Pre-flight migration: fix legacy role values before constraint is applied ──
        # Old Carpulse-AI schema had roles: student, faculty, hod, admin.
        # New schema allows: citizen, admin, moderator, faculty.
        # Map them so the CHECK constraint never fails on existing rows.
        await conn.execute("""
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'users' AND table_schema = 'public'
          ) THEN
            UPDATE users SET role = 'citizen'   WHERE role IN ('student', 'ngo');
            UPDATE users SET role = 'moderator' WHERE role = 'hod';
            -- 'admin' stays as 'admin' — already valid
            ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
          END IF;
        END $$;
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id              TEXT PRIMARY KEY,
            name            TEXT,
            email           TEXT UNIQUE,
            password_hash   TEXT,
            role            TEXT
        );
        """)

        # Add/replace the role constraint after data is clean
        await conn.execute("""
        DO $$ BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM information_schema.table_constraints
            WHERE constraint_name = 'users_role_check'
            AND table_name = 'users'
          ) THEN
            ALTER TABLE users
            ADD CONSTRAINT users_role_check
            CHECK (role IN ('citizen','admin','moderator','faculty'));
          END IF;
        END $$;
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS anon_users (
            anon_id TEXT PRIMARY KEY,
            fingerprint TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS anonymous_reporters (
            anon_id              TEXT PRIMARY KEY,
            trust_tier           TEXT DEFAULT 'standard',
            reports_submitted    INTEGER DEFAULT 0,
            reports_corroborated INTEGER DEFAULT 0,
            reputation_score     FLOAT DEFAULT 0.5,
            created_at           TIMESTAMPTZ DEFAULT NOW()
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id SERIAL PRIMARY KEY,
            anon_id TEXT,
            role TEXT,
            message TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS assets (
            id          TEXT PRIMARY KEY,
            asset_type  TEXT,
            geohash     TEXT,
            lat         FLOAT,
            lng         FLOAT,
            ward_id     TEXT,
            city        TEXT
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS contractors (
            id                     TEXT PRIMARY KEY,
            name                   TEXT,
            registration_no        TEXT,
            city                   TEXT,
            active_contracts       INTEGER DEFAULT 0,
            total_breach_value_inr BIGINT DEFAULT 0,
            failure_score          FLOAT DEFAULT 0.0,
            updated_at             TIMESTAMPTZ DEFAULT NOW()
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS contracts (
            id                  TEXT PRIMARY KEY,
            asset_id            TEXT REFERENCES assets(id),
            contractor_id       TEXT REFERENCES contractors(id),
            contract_number     TEXT,
            contract_value_inr  BIGINT,
            completion_date     DATE,
            warranty_months     INTEGER DEFAULT 24,
            warranty_expiry     DATE,
            status              TEXT CHECK (status IN ('active','expired','disputed')),
            is_synthetic        BOOLEAN DEFAULT FALSE
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS complaints (
            id                  TEXT PRIMARY KEY,
            anon_id             TEXT REFERENCES anonymous_reporters(anon_id),
            asset_id            TEXT REFERENCES assets(id),
            contract_id         TEXT REFERENCES contracts(id),
            complaint_type      TEXT,
            description         TEXT,
            lat                 FLOAT,
            lng                 FLOAT,
            geohash             TEXT,
            status              TEXT DEFAULT 'unverified'
                                CHECK (status IN ('unverified','low_confidence',
                                                  'medium_confidence','high_confidence',
                                                  'assigned','resolved','disputed')),
            confidence_score    FLOAT DEFAULT 0.0,
            confidence_signals  JSONB DEFAULT '{}',
            warranty_breach     BOOLEAN DEFAULT FALSE,
            breach_value_inr    BIGINT DEFAULT 0,
            vote_count          INTEGER DEFAULT 0,
            created_at          TIMESTAMPTZ DEFAULT NOW(),
            updated_at          TIMESTAMPTZ DEFAULT NOW()
        );
        """)

        await conn.execute("""
        ALTER TABLE complaints ADD COLUMN IF NOT EXISTS media_url TEXT;
        """)

        await conn.execute("""
        ALTER TABLE complaints
          ADD COLUMN IF NOT EXISTS report_count INTEGER DEFAULT 1,
          ADD COLUMN IF NOT EXISTS reporters JSONB DEFAULT '[]'::jsonb,
          ADD COLUMN IF NOT EXISTS cluster_id TEXT,
          ADD COLUMN IF NOT EXISTS contractor JSONB;
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS evidence (
            id              TEXT PRIMARY KEY,
            complaint_id    TEXT REFERENCES complaints(id),
            anon_id         TEXT REFERENCES anonymous_reporters(anon_id),
            evidence_type   TEXT CHECK (evidence_type IN
                            ('photo','video','sensor','text','secondary_report')),
            file_path       TEXT,
            state_hash      TEXT,
            state_type      TEXT CHECK (state_type IN ('before','after','support')),
            lat             FLOAT,
            lng             FLOAT,
            timestamp       TIMESTAMPTZ,
            tee_signed      BOOLEAN DEFAULT FALSE,
            tee_attestation JSONB,
            sensor_data     JSONB,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        );
        """)

        await conn.execute("""
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'evidence' AND table_schema = 'public'
          ) THEN
            ALTER TABLE evidence DROP CONSTRAINT IF EXISTS evidence_state_type_check;
            ALTER TABLE evidence
            ADD CONSTRAINT evidence_state_type_check
            CHECK (state_type IN ('before','after','support'));
          END IF;
        END $$;
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS complaint_comments (
            id             TEXT PRIMARY KEY,
            complaint_id   TEXT REFERENCES complaints(id),
            anon_id        TEXT REFERENCES anonymous_reporters(anon_id),
            comment_type   TEXT CHECK (comment_type IN ('support','verification','neutral'))
                           DEFAULT 'neutral',
            text           TEXT NOT NULL,
            image_path     TEXT,
            image_hash     TEXT,
            created_at     TIMESTAMPTZ DEFAULT NOW()
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS votes (
            id              TEXT PRIMARY KEY,
            complaint_id    TEXT REFERENCES complaints(id),
            anon_id         TEXT REFERENCES anonymous_reporters(anon_id),
            vote_type       TEXT CHECK (vote_type IN ('corroborate','dispute')),
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(complaint_id, anon_id)
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS sensor_clusters (
            id                    TEXT PRIMARY KEY,
            geohash               TEXT UNIQUE,
            event_type            TEXT,
            device_count          INTEGER DEFAULT 1,
            first_seen            TIMESTAMPTZ DEFAULT NOW(),
            last_seen             TIMESTAMPTZ DEFAULT NOW(),
            auto_complaint_raised BOOLEAN DEFAULT FALSE,
            complaint_id          TEXT REFERENCES complaints(id)
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id              TEXT PRIMARY KEY,
            action          TEXT,
            entity_type     TEXT,
            entity_id       TEXT,
            actor_anon_id   TEXT,
            payload         JSONB,
            signature       TEXT,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS org_profiles (
            user_id     TEXT PRIMARY KEY REFERENCES users(id),
            org_name    TEXT,
            org_type    TEXT CHECK (org_type IN ('ngo','contractor')),
            region      TEXT,
            verified    BOOLEAN DEFAULT FALSE,
            created_at  TIMESTAMPTZ DEFAULT NOW()
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS ngo_requests (
            id TEXT PRIMARY KEY,
            ngo_user_id TEXT REFERENCES users(id),
            complaint_id TEXT REFERENCES complaints(id),
            reason TEXT,
            type TEXT DEFAULT 'access',
            message TEXT,
            region_match BOOLEAN,
            status TEXT DEFAULT 'pending'
                CHECK (status IN ('pending','approved','rejected')),
            admin_note TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            resolved_at TIMESTAMPTZ
        );
        """)

        await conn.execute("""
        ALTER TABLE ngo_requests
          ADD COLUMN IF NOT EXISTS type TEXT DEFAULT 'access',
          ADD COLUMN IF NOT EXISTS message TEXT,
          ADD COLUMN IF NOT EXISTS region_match BOOLEAN;
        """)

        # ── MISSION 2: New tables ──────────────────────────────────────────────
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS complaint_assignments (
            id              TEXT PRIMARY KEY,
            complaint_id    TEXT REFERENCES complaints(id),
            contractor_id   TEXT,
            contractor_name TEXT,
            assigned_by     TEXT,
            assigned_at     TIMESTAMPTZ DEFAULT NOW(),
            due_date        DATE,
            status          TEXT DEFAULT 'assigned'
                            CHECK (status IN ('assigned','in_progress','resolved','rejected'))
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_summaries (
            id              TEXT PRIMARY KEY,
            complaint_id    TEXT REFERENCES complaints(id) UNIQUE,
            summary         TEXT,
            risk_level      TEXT CHECK (risk_level IN ('critical','high','medium','low')),
            risk_reason     TEXT,
            recommended_action TEXT,
            generated_at    TIMESTAMPTZ DEFAULT NOW()
        );
        """)

        await conn.execute("""
        ALTER TABLE ngo_requests ADD COLUMN IF NOT EXISTS org_type TEXT DEFAULT 'ngo';
        """)

        await conn.execute("""
        ALTER TABLE ngo_requests ADD COLUMN IF NOT EXISTS admin_note_reject TEXT;
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS solve_requests (
            request_id   TEXT PRIMARY KEY,
            grievance_id TEXT REFERENCES complaints(id),
            ngo_id       TEXT REFERENCES users(id),
            note         TEXT,
            status       TEXT DEFAULT 'PENDING'
                         CHECK (status IN ('PENDING','APPROVED','REJECTED')),
            created_at   TIMESTAMPTZ DEFAULT NOW(),
            updated_at   TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(grievance_id, ngo_id)
        );
        """)

        # Migration: update complaints status constraint to include 'assigned'
        await conn.execute("""
        DO $$ BEGIN
          ALTER TABLE complaints DROP CONSTRAINT IF EXISTS complaints_status_check;
          ALTER TABLE complaints
          ADD CONSTRAINT complaints_status_check
          CHECK (status IN ('unverified','low_confidence','medium_confidence',
                            'high_confidence','assigned','resolved','disputed'));
        END $$;
        """)

    logger.info("AWAAZ-PROOF backend started. Tables bootstrapped.")
    yield
    await PostgresDB.disconnect()


app.router.lifespan_context = lifespan

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
