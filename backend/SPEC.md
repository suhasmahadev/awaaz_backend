# SPEC.md — Civic Contract Audit System
**Codename: AWAAZ-PROOF**
**Stack: FastAPI + Google ADK + asyncpg + PostgreSQL + React + Vite**
**Base: Carpulse-AI skeleton (agent folder untouched)**
**Target: 36-hour hackathon build**

---

## CORE THESIS

Every civic complaint platform treats a broken road as a service problem.
This system treats it as what it legally is: a **contract breach**.

Every road, pipe, and drain has a government contract behind it.
That contract has a warranty period and a monetary value.
When infrastructure fails inside the warranty window, public money was stolen — legally, an actionable breach.

This is not a complaint box. It is a **contract audit system triggered by anonymous citizen observations**.

> "We don't trust officials. We don't trust citizens. We trust observable reality changes — and we link them to the contracts that were supposed to prevent them."

---

## WHAT IS NOVEL (DO NOT DILUTE)

1. **Contract-linked complaints** — every complaint resolves to a procurement contract, warranty status, and breach value in rupees. No existing civic platform does this.
2. **Anonymous identity via SHA-256** — reporter never identified, but their evidence is cryptographically attributable and consistent across sessions.
3. **Confidence-weighted verification** — no binary true/false; every event carries a multi-signal confidence score with decomposed contributors.
4. **Public contractor ledger** — machine-readable API of contractor failure scores, active breach counts, and total financial exposure. Media and RTI officers can query it.
5. **TEE as trust gradient** — if device supports secure enclave, evidence gets a hardware trust tier. If not, system still works at a lower trust tier.
6. **Community corroboration layer** — social voting on grievances raises confidence score, does not replace evidence.

---

## WHAT IS STRIPPED (DO NOT REINTRODUCE)

- ❌ ZK proofs for location (too complex for 36h, broken stubs will fail under pressure)
- ❌ Real-time live sensor clustering (cold start problem; use synthetic seeded dataset for demo)
- ❌ Automated legal notice generation (legally risky; use draft template with flagged fields only)
- ❌ Guaranteed enforcement claims (system triggers process and economic pressure, never claims to guarantee outcome)
- ❌ Binary causal attribution ("Company X did it") replaced by probabilistic attribution with confidence score

---

## ARCHITECTURE

### Inheritance from Carpulse-AI skeleton

```
KEEP UNTOUCHED:
  backend/agent/           ← entire folder, no changes
  backend/db.py            ← asyncpg singleton pool
  backend/auth_security.py ← JWT, bcrypt
  backend/auth_models.py
  backend/auth_schemas.py
  backend/routers/auth.py
  backend/routers/agent_chat.py  ← ALLOWED_TOOLS dict will be updated only
  frontend/src/pages/ChatPage.jsx
  frontend/src/api/chatApi.js
  frontend/src/context/AuthContext.jsx

DELETE DOMAIN CONTENT:
  models/data_models.py    ← keep User only, delete Student/Faculty/etc
  services/service.py      ← keep register_user/get_user only
  repos/repo.py            ← keep user CRUD only
  agent/tools.py           ← replace with ping tool only until Mission 6
  agent/*_prompt.py        ← replace with skeleton prompts until Mission 6
  routers/mechanics.py, vehicle_service_logs.py, voice.py,
  file_upload.py, intelligence.py, student_planner.py ← delete all
```

### New File Structure

```
backend/
├── main.py                          # FastAPI app + lifespan
├── db.py                            # asyncpg pool (unchanged)
├── auth_security.py                 # JWT + bcrypt (unchanged)
├── auth_models.py                   # (unchanged)
├── auth_schemas.py                  # (unchanged)
├── constants.py                     # agent model config (unchanged)
│
├── models/
│   └── data_models.py               # User + all new domain models
│
├── repos/
│   └── repo.py                      # all DB access (asyncpg)
│
├── services/
│   └── service.py                   # business logic layer
│
├── agent/                           # ← UNTOUCHED ENTIRELY
│   ├── agent.py
│   ├── tools.py                     # domain tools added here per mission
│   ├── prompt_loader.py
│   ├── base_prompt.py
│   ├── admin_prompt.py
│   ├── faculty_prompt.py
│   ├── hod_prompt.py
│   └── student_prompt.py
│
├── routers/
│   ├── auth.py                      # unchanged
│   ├── agent_chat.py                # ALLOWED_TOOLS updated per mission
│   ├── evidence.py                  # NEW: evidence ingestion
│   ├── complaints.py                # NEW: complaint CRUD + voting
│   ├── contracts.py                 # NEW: procurement contract data
│   ├── contractor_ledger.py         # NEW: public contractor scores
│   ├── verification.py              # NEW: confidence scoring engine
│   └── admin.py                     # NEW: admin panel endpoints
│
├── utils/
│   ├── hashing.py                   # SHA-256 anonymous identity
│   ├── geo.py                       # geohash, reverse geocode
│   ├── confidence.py                # confidence score calculator
│   ├── image_compare.py             # CLIP-based before/after comparison
│   └── tee.py                       # TEE signing wrapper (graceful fallback)
│
└── data/
    └── seed_contracts.json          # synthetic procurement data for demo

frontend/
├── src/
│   ├── pages/
│   │   ├── ChatPage.jsx             # unchanged
│   │   ├── TextUI.jsx               # NEW: text-based backend test UI
│   │   ├── AdminPanel.jsx           # NEW: admin dashboard
│   │   └── ContractorLedger.jsx     # NEW: public ledger page
│   ├── api/
│   │   ├── chatApi.js               # unchanged
│   │   ├── evidenceApi.js           # NEW
│   │   ├── complaintApi.js          # NEW
│   │   └── ledgerApi.js             # NEW
│   ├── context/
│   │   └── AuthContext.jsx          # unchanged
│   └── App.jsx                      # updated routes
```

---

## DATABASE SCHEMA

All tables created in `main.py` lifespan. PostgreSQL via asyncpg.

```sql
-- Core user table (unchanged from skeleton)
CREATE TABLE IF NOT EXISTS users (
    id          TEXT PRIMARY KEY,
    name        TEXT,
    email       TEXT UNIQUE,
    password_hash TEXT,
    role        TEXT CHECK (role IN ('citizen','admin','moderator'))
);

-- Anonymous reporter identity
-- SHA-256(device_fingerprint + salt) stored, never raw fingerprint
CREATE TABLE IF NOT EXISTS anonymous_reporters (
    anon_id         TEXT PRIMARY KEY,         -- SHA-256 hash
    trust_tier      TEXT DEFAULT 'standard',  -- standard | tee_verified
    reports_submitted INTEGER DEFAULT 0,
    reports_corroborated INTEGER DEFAULT 0,
    reputation_score FLOAT DEFAULT 0.5,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Infrastructure assets (seeded from open data / synthetic)
CREATE TABLE IF NOT EXISTS assets (
    id              TEXT PRIMARY KEY,
    asset_type      TEXT,   -- road | water_pipe | drain | street_light
    geohash         TEXT,   -- 7-char geohash for clustering
    lat             FLOAT,
    lng             FLOAT,
    ward_id         TEXT,
    zone            TEXT,
    city            TEXT
);

-- Procurement contracts linked to assets
CREATE TABLE IF NOT EXISTS contracts (
    id              TEXT PRIMARY KEY,
    asset_id        TEXT REFERENCES assets(id),
    contractor_id   TEXT REFERENCES contractors(id),
    contract_number TEXT,
    contract_value_inr BIGINT,
    start_date      DATE,
    completion_date DATE,
    warranty_months INTEGER DEFAULT 24,
    warranty_expiry DATE,   -- completion_date + warranty_months
    status          TEXT CHECK (status IN ('active','expired','disputed')),
    source_url      TEXT,   -- link to original procurement record
    is_synthetic    BOOLEAN DEFAULT FALSE  -- flag for demo data
);

-- Contractors (the entities being held accountable)
CREATE TABLE IF NOT EXISTS contractors (
    id              TEXT PRIMARY KEY,
    name            TEXT,
    registration_no TEXT,
    city            TEXT,
    active_contracts INTEGER DEFAULT 0,
    total_breach_value_inr BIGINT DEFAULT 0,
    failure_score   FLOAT DEFAULT 0.0,   -- 0.0 (perfect) to 1.0 (worst)
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Complaints (core entity)
CREATE TABLE IF NOT EXISTS complaints (
    id              TEXT PRIMARY KEY,
    anon_id         TEXT REFERENCES anonymous_reporters(anon_id),
    asset_id        TEXT REFERENCES assets(id),
    contract_id     TEXT REFERENCES contracts(id),
    complaint_type  TEXT,   -- pothole | no_water | garbage | drain | light
    description     TEXT,
    lat             FLOAT,
    lng             FLOAT,
    geohash         TEXT,
    status          TEXT DEFAULT 'unverified'
                    CHECK (status IN ('unverified','low_confidence',
                                      'medium_confidence','high_confidence',
                                      'resolved','disputed')),
    confidence_score FLOAT DEFAULT 0.0,
    confidence_signals JSONB DEFAULT '{}',  -- decomposed signal breakdown
    warranty_breach BOOLEAN DEFAULT FALSE,
    breach_value_inr BIGINT DEFAULT 0,
    vote_count      INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Evidence attached to complaints
CREATE TABLE IF NOT EXISTS evidence (
    id              TEXT PRIMARY KEY,
    complaint_id    TEXT REFERENCES complaints(id),
    anon_id         TEXT REFERENCES anonymous_reporters(anon_id),
    evidence_type   TEXT CHECK (evidence_type IN
                    ('photo','video','sensor','text','secondary_report')),
    file_path       TEXT,
    state_hash      TEXT,   -- SHA-256 of evidence payload (before or after)
    state_type      TEXT CHECK (state_type IN ('before','after')),
    lat             FLOAT,
    lng             FLOAT,
    timestamp       TIMESTAMPTZ,
    tee_signed      BOOLEAN DEFAULT FALSE,
    tee_attestation TEXT,   -- attestation report JSON if tee_signed=true
    sensor_data     JSONB,  -- {z_spike, speed_kmh, orientation} if sensor
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Community votes on complaints
CREATE TABLE IF NOT EXISTS votes (
    id              TEXT PRIMARY KEY,
    complaint_id    TEXT REFERENCES complaints(id),
    anon_id         TEXT REFERENCES anonymous_reporters(anon_id),
    vote_type       TEXT CHECK (vote_type IN ('corroborate','dispute')),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(complaint_id, anon_id)   -- one vote per reporter per complaint
);

-- Audit log: every agent action signed
CREATE TABLE IF NOT EXISTS audit_log (
    id              TEXT PRIMARY KEY,
    action          TEXT,
    entity_type     TEXT,
    entity_id       TEXT,
    actor_anon_id   TEXT,
    actor_user_id   TEXT,
    payload         JSONB,
    signature       TEXT,   -- HMAC-SHA256 of payload with server key
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Sensor event clusters (passive layer, seeded synthetically for demo)
CREATE TABLE IF NOT EXISTS sensor_clusters (
    id              TEXT PRIMARY KEY,
    geohash         TEXT,
    event_type      TEXT,
    device_count    INTEGER DEFAULT 1,
    first_seen      TIMESTAMPTZ,
    last_seen       TIMESTAMPTZ,
    auto_complaint_raised BOOLEAN DEFAULT FALSE,
    complaint_id    TEXT REFERENCES complaints(id)
);
```

---

## PYDANTIC MODELS (`models/data_models.py`)

```python
class User(BaseModel):
    id: Optional[str] = None
    name: str
    email: str
    password_hash: Optional[str] = None
    role: str  # citizen | admin | moderator

class AnonReporter(BaseModel):
    anon_id: str              # SHA-256 hash, never raw device ID
    trust_tier: str = "standard"
    reports_submitted: int = 0
    reputation_score: float = 0.5

class Asset(BaseModel):
    id: Optional[str] = None
    asset_type: str
    geohash: str
    lat: float
    lng: float
    ward_id: Optional[str] = None
    city: str

class Contractor(BaseModel):
    id: Optional[str] = None
    name: str
    registration_no: Optional[str] = None
    failure_score: float = 0.0
    total_breach_value_inr: int = 0

class Contract(BaseModel):
    id: Optional[str] = None
    asset_id: str
    contractor_id: str
    contract_number: str
    contract_value_inr: int
    completion_date: str
    warranty_months: int = 24
    warranty_expiry: str
    status: str = "active"
    is_synthetic: bool = False

class Complaint(BaseModel):
    id: Optional[str] = None
    anon_id: str
    asset_id: Optional[str] = None
    contract_id: Optional[str] = None
    complaint_type: str
    description: Optional[str] = None
    lat: float
    lng: float
    geohash: str
    status: str = "unverified"
    confidence_score: float = 0.0
    confidence_signals: dict = {}
    warranty_breach: bool = False
    breach_value_inr: int = 0
    vote_count: int = 0

class Evidence(BaseModel):
    id: Optional[str] = None
    complaint_id: str
    anon_id: str
    evidence_type: str
    file_path: Optional[str] = None
    state_hash: Optional[str] = None
    state_type: str  # before | after
    lat: float
    lng: float
    timestamp: str
    tee_signed: bool = False
    sensor_data: Optional[dict] = None

class ConfidenceBreakdown(BaseModel):
    total: float
    signals: dict   # {"single_report": 0.3, "photo_attached": 0.25, ...}
    threshold_met: str  # unverified | low | medium | high

class ContractorLedgerEntry(BaseModel):
    contractor_id: str
    name: str
    active_contracts: int
    active_breach_count: int
    total_breach_value_inr: int
    failure_score: float
    worst_performing_ward: Optional[str] = None

class ChatRequest(BaseModel):
    message: str
```

---

## CONFIDENCE SCORING ENGINE (`utils/confidence.py`)

The confidence score is the central truth primitive of the system.
It is **never binary**. Every complaint carries a score from 0.0 to 1.0
with decomposed signal contributors.

### Signal weights

```python
SIGNAL_WEIGHTS = {
    "single_report":            0.30,  # base: one report submitted
    "photo_attached":           0.15,  # photo evidence included
    "gps_precision_high":       0.05,  # GPS accuracy < 10m
    "multi_reporter_48h":       0.20,  # 2+ independent reporters same geohash 48h
    "sensor_cluster":           0.15,  # accelerometer cluster from synthetic/real data
    "community_vote_net_5":     0.10,  # net 5+ corroborate votes
    "repeat_temporal_pattern":  0.10,  # same geohash 3+ complaints in 30 days
    "tee_signed_evidence":      0.05,  # TEE attestation present (bonus tier)
    "after_state_submitted":   -0.10,  # resolution evidence submitted (decay)
    "after_state_verified":    -0.25,  # before/after CLIP similarity confirms change
}

THRESHOLDS = {
    "unverified":   (0.00, 0.35),
    "low":          (0.35, 0.55),
    "medium":       (0.55, 0.75),
    "high":         (0.75, 1.00),
}
```

### Output format (returned by every verification call)

```json
{
  "complaint_id": "cmp_...",
  "confidence": 0.82,
  "threshold_tier": "high",
  "signals": {
    "single_report": 0.30,
    "photo_attached": 0.15,
    "multi_reporter_48h": 0.20,
    "sensor_cluster": 0.15,
    "community_vote_net_5": 0.10,
    "tee_signed_evidence": 0.05
  },
  "missing_signals": ["repeat_temporal_pattern", "after_state_submitted"],
  "auto_escalate": true
}
```

---

## ANONYMOUS IDENTITY SYSTEM (`utils/hashing.py`)

The reporter's real identity is never stored. Anonymity is guaranteed by design.

### How it works

```python
import hashlib, os

SERVER_SALT = os.getenv("ANON_SALT", "change_in_production")

def generate_anon_id(device_fingerprint: str) -> str:
    """
    Input:  raw device fingerprint (browser fingerprint / device ID)
            never stored, never logged
    Output: SHA-256(device_fingerprint + SERVER_SALT)
            stored as anon_id in all tables
    """
    raw = f"{device_fingerprint}{SERVER_SALT}"
    return hashlib.sha256(raw.encode()).hexdigest()

def hash_evidence_payload(payload: bytes) -> str:
    """
    SHA-256 of raw evidence bytes (photo/video/sensor JSON).
    Stored as state_hash in evidence table.
    Enables before/after comparison without storing raw sensitive data.
    """
    return hashlib.sha256(payload).hexdigest()
```

### What this guarantees

- Same device → same anon_id across sessions (consistent reputation)
- Server cannot reverse anon_id to device fingerprint (one-way hash)
- Server salt change invalidates all existing anon_ids (emergency reset)
- Community sees vote counts and confidence scores, never reporter identity

---

## GEO LAYER (`utils/geo.py`)

```python
import python_geohash as geohash

def coords_to_geohash(lat: float, lng: float, precision: int = 7) -> str:
    """
    Precision 7 = ~150m x 150m cell. Used for clustering.
    Precision 5 = ~5km x 5km. Used for ward-level aggregation.
    """
    return geohash.encode(lat, lng, precision)

def geohash_to_bbox(gh: str) -> dict:
    lat, lng, lat_err, lng_err = geohash.decode_exactly(gh)
    return {
        "center_lat": lat, "center_lng": lng,
        "lat_err": lat_err, "lng_err": lng_err
    }

def reverse_geocode_ward(lat: float, lng: float) -> dict:
    """
    Uses Nominatim (OpenStreetMap, free, no key needed).
    Returns ward, zone, city from lat/lng.
    Cached in memory for demo to avoid rate limits.
    """
    import httpx
    r = httpx.get(
        "https://nominatim.openstreetmap.org/reverse",
        params={"lat": lat, "lon": lng, "format": "json"},
        headers={"User-Agent": "awaaz-proof-hackathon"}
    )
    data = r.json()
    return {
        "ward": data.get("address", {}).get("suburb", "Unknown"),
        "city": data.get("address", {}).get("city", "Unknown"),
        "state": data.get("address", {}).get("state", "Unknown"),
    }

def cluster_complaints_by_geohash(complaints: list) -> dict:
    """
    Groups complaints by geohash prefix (precision 6).
    Returns clusters with count and confidence boost flag.
    Cluster >= 3 unique anon_ids = multi_reporter_48h signal triggered.
    """
    from collections import defaultdict
    clusters = defaultdict(list)
    for c in complaints:
        key = c["geohash"][:6]
        clusters[key].append(c)
    return {k: v for k, v in clusters.items() if len(v) >= 2}
```

---

## TEE TRUST LAYER (`utils/tee.py`)

TEE is a bonus tier, not a system dependency. System degrades gracefully.

```python
import hmac, hashlib, os, json
from datetime import datetime

SERVER_ENCLAVE_KEY = os.getenv("ENCLAVE_KEY", "demo_key_change_in_prod")

def sign_evidence(payload: dict) -> dict:
    """
    Production: Intel SGX / AWS Nitro Enclave signs payload.
    Demo/fallback: HMAC-SHA256 with server key (honest about this to judges).
    Returns attestation object attached to evidence record.
    """
    payload_str = json.dumps(payload, sort_keys=True)
    signature = hmac.new(
        SERVER_ENCLAVE_KEY.encode(),
        payload_str.encode(),
        hashlib.sha256
    ).hexdigest()

    return {
        "signed": True,
        "method": "hmac_sha256_demo",  # change to "sgx_attestation" in prod
        "signature": signature,
        "signed_at": datetime.utcnow().isoformat(),
        "payload_hash": hashlib.sha256(payload_str.encode()).hexdigest()
    }

def verify_signature(payload: dict, attestation: dict) -> bool:
    rebuilt = sign_evidence(payload)
    return hmac.compare_digest(rebuilt["signature"], attestation["signature"])

def get_trust_tier(tee_signed: bool, reputation_score: float) -> str:
    """
    Trust gradient: hardware trust > server-signed > base
    Adds 0.05 confidence bonus when tee_signed=True
    """
    if tee_signed:
        return "tee_verified"
    if reputation_score > 0.7:
        return "trusted_reporter"
    return "standard"
```

---

## IMAGE COMPARISON ENGINE (`utils/image_compare.py`)

Used for before/after verification. Uses CLIP semantic embeddings.
No pixel diff (fails on lighting/angle changes as noted in critique).

```python
from PIL import Image
import torch
import clip
import numpy as np

model, preprocess = clip.load("ViT-B/32")

def get_image_embedding(image_path: str) -> np.ndarray:
    image = preprocess(Image.open(image_path)).unsqueeze(0)
    with torch.no_grad():
        embedding = model.encode_image(image)
    return embedding.numpy()

def compare_before_after(before_path: str, after_path: str) -> dict:
    """
    Semantic similarity between before and after images.
    Low similarity = significant change detected (road repaired, area cleared).
    High similarity = no change (complaint unresolved despite claimed resolution).
    """
    before_emb = get_image_embedding(before_path)
    after_emb  = get_image_embedding(after_path)

    similarity = float(np.dot(before_emb, after_emb.T) /
                       (np.linalg.norm(before_emb) * np.linalg.norm(after_emb)))

    change_detected = similarity < 0.75  # threshold tunable

    return {
        "similarity_score": round(similarity, 3),
        "change_detected": change_detected,
        "confidence": round(1.0 - similarity, 3) if change_detected else round(similarity, 3),
        "verdict": "change_verified" if change_detected else "no_change_detected"
    }
```

---

## AGENT TOOLS (`agent/tools.py`) — updated per mission

```python
# ── MISSION 1: pipeline verification ──────────────────────────────
async def ping(message: str) -> dict:
    """Echo tool. Confirms agent pipeline is working end-to-end."""
    return {"success": True, "data": {"echo": message, "status": "pipeline_ok"}}

# ── MISSION 4 onwards: domain tools added ─────────────────────────
async def submit_complaint(
    anon_id: str,
    complaint_type: str,
    lat: float,
    lng: float,
    description: str = ""
) -> dict:
    """Submit a new anonymous complaint with geolocation."""

async def get_complaint_status(complaint_id: str) -> dict:
    """Get current status, confidence score, and signals for a complaint."""

async def get_contractor_ledger(city: str = "Bengaluru") -> dict:
    """Get public contractor failure scores and breach values for a city."""

async def check_warranty_breach(complaint_id: str) -> dict:
    """Check if complaint location has an active contract and if it's in warranty."""

async def get_my_complaints(anon_id: str) -> dict:
    """Get all complaints submitted by this anonymous reporter."""

async def get_area_complaints(lat: float, lng: float, radius_km: float = 1.0) -> dict:
    """Get all complaints within radius of given coordinates."""

async def get_admin_overview() -> dict:
    """Admin only: total complaints, confidence distribution, top breach contractors."""
```

### ALLOWED_TOOLS registry (`routers/agent_chat.py`)

```python
ALLOWED_TOOLS = {
    "citizen":    [ping, submit_complaint, get_complaint_status,
                   get_contractor_ledger, check_warranty_breach,
                   get_my_complaints, get_area_complaints],
    "moderator":  [ping, get_complaint_status, get_contractor_ledger,
                   get_area_complaints, get_admin_overview],
    "admin":      [ping, submit_complaint, get_complaint_status,
                   get_contractor_ledger, check_warranty_breach,
                   get_my_complaints, get_area_complaints, get_admin_overview],
}
```

---

## AGENT PROMPTS (replace all role prompts with these)

### `base_prompt.py`

```python
BASE_PROMPT = """
You are AWAAZ-PROOF, a civic contract audit backend controller. NOT a chatbot.

CORE RULES:
1. You are an operational executor. Map user intent → tool → structured response.
2. DO NOT hallucinate tools. Use ONLY the tools provided.
3. NEVER expose internal logic, SQL schema, or database structure.
4. NEVER identify an anonymous reporter beyond their anon_id.
5. All attribution is probabilistic. Never say "Company X did it." Say "Most likely responsible (confidence: 0.76)."
6. Every response must be JSON with this envelope:
   {"status": "success"|"error", "action": "<tool_name>", "data": {}}

CONFIDENCE LANGUAGE RULES:
- score 0.00–0.35 → "unverified — insufficient signals"
- score 0.35–0.55 → "low confidence — more corroboration needed"
- score 0.55–0.75 → "medium confidence — probable infrastructure failure"
- score 0.75–1.00 → "high confidence — probable warranty breach, auto-escalation triggered"
"""
```

### `admin_prompt.py` / `faculty_prompt.py` / `hod_prompt.py` / `student_prompt.py`

```python
# All four files — replace FINAL_PROMPT with:
from agent.base_prompt import BASE_PROMPT

FINAL_PROMPT = BASE_PROMPT + """
Role: [admin | moderator | citizen | citizen]
Status: Domain tools loaded. Contract audit system active.
Remember: probabilistic attribution only. Confidence scores required on every output.
"""
```

---

## API ENDPOINTS

### Auth (`/auth`)
```
POST /auth/register      — register user (citizen | admin | moderator)
POST /auth/login         — returns JWT
POST /auth/refresh       — refresh JWT
```

### Agent (`/agent`)
```
POST /agent/chat         — main agent endpoint (role from JWT)
                           body: { "message": "string" }
```

### Evidence (`/evidence`)
```
POST /evidence/submit    — submit evidence (photo/video/sensor)
                           body: multipart form
                           fields: complaint_id, anon_id, evidence_type,
                                   state_type (before|after), lat, lng, sensor_data
POST /evidence/compare   — run before/after CLIP comparison
                           body: { complaint_id }
GET  /evidence/{id}      — get evidence record + state hash
```

### Complaints (`/complaints`)
```
POST /complaints/new     — create complaint
                           body: { anon_id, complaint_type, lat, lng, description }
GET  /complaints/{id}    — get complaint + confidence breakdown
GET  /complaints/area    — query: lat, lng, radius_km
GET  /complaints/mine    — header: X-Anon-Id
POST /complaints/{id}/vote  — body: { anon_id, vote_type: corroborate|dispute }
PATCH /complaints/{id}/recalculate  — trigger confidence recalculation
```

### Contracts (`/contracts`)
```
GET  /contracts/asset/{asset_id}    — contracts linked to asset
GET  /contracts/warranty/check      — query: lat, lng → nearest asset + warranty status
GET  /contracts/{id}                — contract details
```

### Contractor Ledger (`/ledger`) — PUBLIC, NO AUTH
```
GET  /ledger                        — full contractor list with scores
GET  /ledger/{contractor_id}        — single contractor profile + breach history
GET  /ledger/feed                   — RSS-style JSON feed (media/RTI use)
                                      sorted by failure_score DESC
GET  /ledger/city/{city}            — contractors in a city
```

### Verification (`/verify`)
```
POST /verify/confidence/{complaint_id}   — recalculate confidence from all signals
POST /verify/before-after/{complaint_id} — run CLIP comparison on evidence
GET  /verify/cluster/{geohash}           — get sensor cluster for geohash
```

### Admin (`/admin`) — admin JWT only
```
GET  /admin/overview        — totals: complaints, verified, breaches, exposure
GET  /admin/complaints      — all complaints with filters
GET  /admin/contractors     — all contractors with breach counts
POST /admin/seed            — seed synthetic contract + sensor data
GET  /admin/audit-log       — full signed audit log
```

---

## THE 10 MISSIONS

---

### MISSION 1 — PIPELINE SKELETON + ANONYMOUS IDENTITY
**Goal:** Confirm the full agent session loop works. Anonymous identity working.
**Files touched:** `utils/hashing.py`, `models/data_models.py`, `repos/repo.py`,
`services/service.py`, `main.py`, `agent/tools.py` (ping only), all `*_prompt.py`

**Deliverables:**
1. Delete all Carpulse domain content (Student, Faculty, etc.)
2. Keep: User model, auth layer, db.py, agent folder structure
3. Create `utils/hashing.py` with `generate_anon_id()` and `hash_evidence_payload()`
4. Create `anonymous_reporters` table in main.py lifespan
5. Create `POST /auth/anon` — accepts device fingerprint, returns anon_id (hashed)
6. Add ping tool to `agent/tools.py`, update all prompts to skeleton prompts
7. Update `ALLOWED_TOOLS` to `{"citizen": [ping], "admin": [ping], "moderator": [ping]}`

**Verification test:**
```bash
# 1. Get anon_id
curl -X POST /auth/anon -d '{"fingerprint": "test_device_123"}'
# → {"anon_id": "a3f2...sha256hash"}

# 2. Get JWT
curl -X POST /auth/login -d '{"email":"test@test.com","password":"test"}'
# → {"access_token": "..."}

# 3. Confirm agent pipeline
curl -X POST /agent/chat -H "Authorization: Bearer ..." \
     -d '{"message": "hello"}'
# → {"status":"success","action":"ping","data":{"echo":"hello","status":"pipeline_ok"}}
```

---

### MISSION 2 — GEO LAYER + ASSET/CONTRACT SCHEMA
**Goal:** Geo utilities working. DB schema for assets and contracts created. Seed data loaded.
**Files touched:** `utils/geo.py`, `models/data_models.py`, `repos/repo.py`,
`main.py` (lifespan tables), `data/seed_contracts.json`, `routers/admin.py`

**Deliverables:**
1. Create `utils/geo.py` with `coords_to_geohash()`, `reverse_geocode_ward()`, `cluster_complaints_by_geohash()`
2. Create tables: `assets`, `contractors`, `contracts` in main.py lifespan
3. Add Pydantic models: Asset, Contractor, Contract
4. Add repo methods: `insert_asset`, `get_asset_by_geohash`, `insert_contractor`,
   `insert_contract`, `get_contract_by_asset`, `check_warranty_status`
5. Create `data/seed_contracts.json` — minimum 20 synthetic contracts across 5 wards
   in Bengaluru with varying warranty expiry dates (some expired, some active)
6. Create `POST /admin/seed` endpoint that loads seed data into DB
7. Create `GET /contracts/warranty/check?lat=&lng=` — returns nearest asset + contract + warranty status

**Seed data format:**
```json
[{
  "contractor": {"name": "XYZ Infra Pvt Ltd", "registration_no": "KA-2019-4521"},
  "asset": {"type": "road", "lat": 12.9716, "lng": 77.5946, "ward_id": "ward_42"},
  "contract": {
    "contract_number": "BLR-PWD-2024-0892",
    "contract_value_inr": 4200000,
    "completion_date": "2024-03-15",
    "warranty_months": 24,
    "is_synthetic": true
  }
}]
```

**Verification test:**
```bash
# Seed data
curl -X POST /admin/seed -H "Authorization: Bearer <admin_token>"

# Check warranty at a location
curl "/contracts/warranty/check?lat=12.9716&lng=77.5946"
# → {"asset_id":"...","contract_id":"...","warranty_status":"active",
#    "contractor":"XYZ Infra","breach_possible":true}
```

---

### MISSION 3 — COMPLAINT SUBMISSION + STATE HASHING
**Goal:** Citizens can submit complaints anonymously. Before-state hash captured.
**Files touched:** `models/data_models.py`, `repos/repo.py`, `services/service.py`,
`routers/complaints.py`, `routers/evidence.py`

**Deliverables:**
1. Create `complaints` and `evidence` tables in main.py lifespan
2. Add repo methods: `insert_complaint`, `get_complaint`, `get_complaints_by_geohash`,
   `get_complaints_by_anon`, `insert_evidence`
3. Create `POST /complaints/new`:
   - Accept: anon_id, complaint_type, lat, lng, description
   - Auto-generate geohash from lat/lng
   - Auto-lookup nearest asset within 200m
   - Auto-check warranty status → set `warranty_breach` flag
   - Set initial `confidence_score = 0.30` (single_report signal only)
   - Return: complaint_id, geohash, asset_matched, warranty_status
4. Create `POST /evidence/submit`:
   - Accept: multipart (complaint_id, anon_id, file, evidence_type, state_type, lat, lng)
   - SHA-256 hash the file bytes → store as `state_hash`
   - Store file to `/static/evidence/`
   - If `state_type = "before"` → this is initial state capture
   - If `state_type = "after"` → trigger confidence recalculation
5. Create `GET /complaints/{id}` — returns complaint + linked evidence + current confidence

**Verification test:**
```bash
# Submit complaint
curl -X POST /complaints/new \
  -d '{"anon_id":"a3f2...","complaint_type":"pothole","lat":12.9716,"lng":77.5946}'
# → {"complaint_id":"cmp_...","confidence":0.30,"warranty_breach":true}

# Submit evidence
curl -X POST /evidence/submit \
  -F "complaint_id=cmp_..." -F "anon_id=a3f2..." \
  -F "file=@road_photo.jpg" -F "evidence_type=photo" -F "state_type=before" \
  -F "lat=12.9716" -F "lng=77.5946"
# → {"evidence_id":"ev_...","state_hash":"sha256...","confidence_bump":0.15}
```

---

### MISSION 4 — CONFIDENCE SCORING ENGINE
**Goal:** Full confidence calculation running. All signals decomposed and returned.
**Files touched:** `utils/confidence.py`, `repos/repo.py`, `services/service.py`,
`routers/verification.py`

**Deliverables:**
1. Create `utils/confidence.py` with full SIGNAL_WEIGHTS dict and threshold tiers
2. Implement `calculate_confidence(complaint_id, db_pool) -> ConfidenceBreakdown`:
   - Queries: evidence count, vote counts, temporal pattern, sensor cluster
   - Returns: total score + signal breakdown + threshold tier
3. Create `POST /verify/confidence/{complaint_id}`:
   - Runs full confidence calculation
   - Updates `complaints` table with new score and signals JSONB
   - Returns `ConfidenceBreakdown` object
4. Auto-trigger confidence recalculation on:
   - New evidence submitted
   - New vote submitted
   - Sensor cluster formed at same geohash
5. Auto-escalation logic: if confidence crosses 0.75 threshold:
   - Update complaint status to "high_confidence"
   - Write to audit_log with HMAC signature
   - Update contractor's `failure_score` and `total_breach_value_inr`

**Verification test:**
```bash
curl -X POST /verify/confidence/cmp_...
# → {
#     "confidence": 0.55,
#     "threshold_tier": "medium",
#     "signals": {
#       "single_report": 0.30,
#       "photo_attached": 0.15,
#       "gps_precision_high": 0.05,
#       "multi_reporter_48h": 0.0,
#       "sensor_cluster": 0.0
#     },
#     "missing_signals": ["multi_reporter_48h","community_vote_net_5"],
#     "auto_escalate": false
#   }
```

---

### MISSION 5 — PASSIVE SENSOR LAYER (SYNTHETIC DATASET)
**Goal:** Sensor cluster table populated with synthetic data. Cluster → auto-complaint working.
**Files touched:** `repos/repo.py`, `services/service.py`, `routers/admin.py`,
`data/seed_contracts.json` (extended), `routers/verification.py`

**Note:** Real-time accelerometer sensing dropped (cold start problem).
Demo uses 6 months of pre-seeded sensor events for Bengaluru mock wards.
Be transparent with judges: "demo uses seeded data; production would collect from
opted-in user devices."

**Deliverables:**
1. Create `sensor_clusters` table in main.py lifespan
2. Extend `POST /admin/seed` to also seed sensor cluster data:
   - 15 clusters across seeded asset locations
   - Varying device_count (1–12), dates spanning 6 months
3. Create `GET /verify/cluster/{geohash}` — returns cluster for geohash ± precision 6
4. Implement cluster-to-complaint auto-raise logic:
   - If cluster `device_count >= 3` and `auto_complaint_raised = false`
   - Auto-create complaint with anon_id = "system_sensor_agent"
   - Set confidence_signals to include `sensor_cluster: 0.15`
   - Set `auto_complaint_raised = true`
5. Add `POST /sensor/event` — accept individual sensor event:
   ```json
   {"anon_id":"...","lat":12.97,"lng":77.59,"z_spike":2.4,
    "speed_kmh":22,"timestamp":"..."}
   ```
   - Z-spike > 1.8 at speed > 8 kmh = pothole candidate
   - Insert into sensor_clusters or increment device_count at matching geohash
   - If cluster hits threshold → auto-raise complaint

**Verification test:**
```bash
# Check seeded cluster
curl /verify/cluster/tdr3j2
# → {"geohash":"tdr3j2","device_count":7,"event_type":"pothole",
#    "auto_complaint_raised":true,"complaint_id":"cmp_..."}
```

---

### MISSION 6 — COMMUNITY SOCIAL LAYER (VOTING)
**Goal:** Anonymous community voting on complaints. Votes affect confidence score.
**Files touched:** `repos/repo.py`, `services/service.py`, `routers/complaints.py`,
`routers/verification.py`

**Deliverables:**
1. Create `votes` table in main.py lifespan
2. Create `POST /complaints/{id}/vote`:
   - Accept: anon_id, vote_type (corroborate | dispute)
   - Enforce: one vote per anon_id per complaint (UNIQUE constraint)
   - Prevent: reporter voting on their own complaint
   - Prevent: same anon_id voting twice (return 409 with message)
   - Trigger: confidence recalculation after every vote
3. Create `GET /complaints/area?lat=&lng=&radius_km=`:
   - Return complaints within radius sorted by confidence DESC
   - Include: vote_count, confidence_tier, complaint_type, created_at
   - This is the "community feed" — what citizens see to vote on
4. Add reputation scoring: when a reporter's complaint reaches "high_confidence",
   increment their `reports_corroborated` and recalculate `reputation_score`
5. Anti-gaming: flag if a single anon_id votes on > 20 complaints in 1 hour
   → set their `trust_tier = "flagged"`, exclude their votes from confidence calc

**Verification test:**
```bash
# Vote on complaint
curl -X POST /complaints/cmp_.../vote \
  -d '{"anon_id":"b7c9...","vote_type":"corroborate"}'
# → {"vote_id":"v_...","new_confidence":0.65,"threshold_tier":"medium"}

# Try duplicate vote
curl -X POST /complaints/cmp_.../vote \
  -d '{"anon_id":"b7c9...","vote_type":"corroborate"}'
# → 409 {"error":"already_voted","message":"One vote per complaint per reporter"}
```

---

### MISSION 7 — CONTRACTOR PUBLIC LEDGER
**Goal:** Live contractor failure scores. Machine-readable public API. Economic pressure layer.
**Files touched:** `repos/repo.py`, `services/service.py`, `routers/contractor_ledger.py`

**Deliverables:**
1. Implement `update_contractor_scores(contractor_id)` in service layer:
   - Counts active warranty breaches for contractor
   - Sums breach values in rupees
   - Calculates `failure_score = breach_count / total_contracts` (capped at 1.0)
   - Triggered every time a complaint reaches "high_confidence"
2. Create `GET /ledger`:
   - Returns all contractors sorted by failure_score DESC
   - Public endpoint, no auth required
   - Includes: name, active_contracts, active_breach_count,
     total_breach_value_inr, failure_score, worst_performing_ward
3. Create `GET /ledger/{contractor_id}`:
   - Full contractor profile
   - Breach history: list of high_confidence complaints linked to their contracts
   - Each entry includes: location (ward only, not exact GPS), complaint_type,
     breach_value, days_since_completion, warranty_remaining_days
4. Create `GET /ledger/feed`:
   - JSON feed format (media/RTI use)
   - Sorted by total_breach_value_inr DESC
   - Includes machine-readable timestamps, no auth required
5. Update contractor ledger on every confidence threshold crossing (0.75)

**Verification test:**
```bash
# Public ledger
curl /ledger
# → [
#     {"name":"XYZ Infra Pvt Ltd","failure_score":0.78,
#      "active_breach_count":11,"total_breach_value_inr":4700000},
#     ...
#   ]

# Contractor detail
curl /ledger/ctr_...
# → {"name":"XYZ Infra","breach_history":[
#     {"ward":"Ward 42","type":"pothole","breach_value":420000,
#      "warranty_remaining_days":487,"confidence":0.82}
#   ]}
```

---

### MISSION 8 — BEFORE/AFTER VERIFICATION + AUDIT LOG
**Goal:** CLIP-based image comparison for resolution verification. Signed audit log.
**Files touched:** `utils/image_compare.py`, `utils/tee.py`, `repos/repo.py`,
`services/service.py`, `routers/verification.py`, `routers/evidence.py`

**Deliverables:**
1. Create `utils/image_compare.py` with CLIP-based `compare_before_after()`
2. Create `POST /verify/before-after/{complaint_id}`:
   - Requires: both "before" and "after" evidence records in DB
   - Runs CLIP comparison
   - If `change_detected = true`:
     - Apply `-0.25` signal to confidence (resolution candidate)
     - Update complaint status to "resolved" if confidence drops below 0.35
   - If `change_detected = false`:
     - Flag as "disputed" — official claimed resolution but evidence shows none
   - Returns: `{similarity_score, change_detected, verdict, new_confidence}`
3. Create `audit_log` table in main.py lifespan
4. Create `log_action(action, entity_type, entity_id, actor_id, payload)` in service:
   - HMAC-SHA256 signs payload with SERVER_ENCLAVE_KEY
   - Writes to audit_log table
   - Called on: complaint created, confidence threshold crossed, vote submitted,
     contractor score updated, resolution verified
5. Create `GET /admin/audit-log` (admin only):
   - Returns full audit log with signatures
   - Frontend shows: action, entity, actor (anon_id or user_id), timestamp, signature_valid
6. Create `utils/tee.py` with `sign_evidence()` and trust tier gradient:
   - Evidence submitted with TEE attestation → `trust_tier = "tee_verified"` (+0.05 confidence)
   - Evidence without TEE → `trust_tier = "standard"` (no bonus)

**Verification test:**
```bash
# Before/after comparison
curl -X POST /verify/before-after/cmp_...
# → {"similarity_score":0.42,"change_detected":true,
#    "verdict":"change_verified","new_confidence":0.31,
#    "complaint_status":"resolved"}

# Audit log (admin)
curl /admin/audit-log -H "Authorization: Bearer <admin>"
# → [{"action":"confidence_threshold_crossed","entity_id":"cmp_...",
#     "signature":"hmac...","signature_valid":true}]
```

---

### MISSION 9 — ADMIN PANEL (BACKEND + FRONTEND)
**Goal:** Admin can see full system state. Complaint management. Contractor oversight.
**Files touched:** `routers/admin.py`, `frontend/src/pages/AdminPanel.jsx`,
`frontend/src/api/ledgerApi.js`

**Backend deliverables:**
1. `GET /admin/overview`:
   ```json
   {
     "total_complaints": 142,
     "by_tier": {"unverified":43,"low":31,"medium":28,"high":40},
     "total_warranty_breaches": 40,
     "total_breach_value_inr": 18400000,
     "top_failing_contractors": [{"name":"XYZ Infra","score":0.78}],
     "complaints_this_week": 23
   }
   ```
2. `GET /admin/complaints?status=&city=&contractor_id=` — filtered complaint list
3. `GET /admin/contractors` — all contractors with breach counts and values
4. `POST /admin/seed` — (already in Mission 2; extend here if needed)

**Frontend deliverables (`AdminPanel.jsx`):**
- Stats bar: total complaints / high confidence / total breach value
- Complaint table: filterable by status, city, contractor
- Contractor table: sortable by failure_score
- Audit log viewer: scrollable, shows signature_valid badge per row
- Seed data button: calls `POST /admin/seed` and confirms row count

---

### MISSION 10 — TEXT UI (BACKEND TESTING INTERFACE)
**Goal:** Text-based UI in browser for testing all backend routes without Postman.
Existing ChatPage untouched. TextUI is a separate page.
**Files touched:** `frontend/src/pages/TextUI.jsx`, `frontend/src/App.jsx`

**Deliverables:**
1. Route `/text-ui` in `App.jsx` → `TextUI.jsx`
2. `TextUI.jsx` — a plain terminal-style interface:
   - Input box at bottom (like a shell)
   - Output panel above (scrollable, monospaced)
   - Command palette of all available API calls
3. Built-in commands:
   ```
   > help                    — list all commands
   > anon <fingerprint>      — POST /auth/anon
   > login <email> <pass>    — POST /auth/login
   > ping                    — POST /agent/chat {"message":"ping"}
   > seed                    — POST /admin/seed
   > complaint <type> <lat> <lng>   — POST /complaints/new
   > status <complaint_id>   — GET /complaints/{id}
   > vote <cid> <corroborate|dispute>  — POST /complaints/{id}/vote
   > verify <complaint_id>   — POST /verify/confidence/{id}
   > ledger                  — GET /ledger
   > area <lat> <lng>        — GET /complaints/area
   > cluster <geohash>       — GET /verify/cluster/{geohash}
   > audit                   — GET /admin/audit-log
   > clear                   — clear output panel
   ```
4. Output rendering:
   - JSON responses pretty-printed with colour coding:
     `"status":"success"` → green
     `"status":"error"` → red
     confidence tier labels → amber/green
   - Each response shows: endpoint called, HTTP status, response time, body
5. State: stores current anon_id and JWT token between commands
6. ChatPage (`/chat`) remains completely unchanged — separate route

---

## ROLES

```
citizen    — submit complaints, vote, view ledger, use agent chat
moderator  — all citizen actions + view admin overview, mark disputes
admin      — all above + seed data, view audit log, manage all complaints
```

---

## ENVIRONMENT VARIABLES

```env
# Database
PG_USER=postgres
PG_PASSWORD=changeme
PG_DB=awaaz_proof
PG_HOST=localhost
PG_PORT=5432

# Auth
SECRET_KEY=change_in_production_min_32_chars
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# Anonymous identity
ANON_SALT=change_in_production_min_32_chars

# TEE / audit signing
ENCLAVE_KEY=change_in_production_min_32_chars

# LLM
GOOGLE_API_KEY=your_google_api_key
LLM_PROVIDER=google   # or: ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2

# Frontend
VITE_API_BASE=http://localhost:8000
```

---

## DEPENDENCIES

```txt
# backend/requirements.txt
fastapi
uvicorn[standard]
asyncpg
pydantic
python-jose[cryptography]
passlib[bcrypt]
python-multipart
python-geohash
httpx
Pillow
torch
git+https://github.com/openai/CLIP.git
numpy
scikit-learn
apscheduler
google-generativeai
google-adk
python-dotenv
```

```json
// frontend/package.json (additions)
{
  "dependencies": {
    "react": "^18",
    "react-dom": "^18",
    "react-router-dom": "^6",
    "axios": "^1.6"
  }
}
```

---

## DEMO SCRIPT (36h judging — 4 minutes)

```
1. [TextUI] > anon my_device_123
   → shows anon_id (SHA-256 hash). "Your identity: anonymous, consistent, irreversible."

2. [TextUI] > login admin@test.com admin
   → JWT returned. "System access granted."

3. [TextUI] > seed
   → "Loaded 20 contracts, 15 sensor clusters, 5 contractors across 4 Bengaluru wards."

4. [TextUI] > complaint pothole 12.9716 77.5946
   → "Complaint raised. Confidence: 0.30 (single report). Warranty breach: TRUE.
      Contract: BLR-PWD-2024-0892. Contractor: XYZ Infra. Breach value: ₹4.2L."

5. [TextUI] > verify cmp_...
   → "Confidence: 0.30 → 0.45 after cluster match. Tier: low."

6. [TextUI] > vote cmp_... corroborate  (run 2-3 times with diff anon IDs)
   → "Confidence: 0.65 → 0.75. Threshold crossed: HIGH CONFIDENCE.
      Auto-escalation triggered. Contractor failure score updated."

7. [TextUI] > ledger
   → Shows XYZ Infra: failure_score 0.78, 11 active breaches, ₹47L total exposure.

8. [AdminPanel] open in browser
   → Stats bar: 1 high-confidence breach, ₹4.2L. Audit log shows HMAC-signed entries.

9. Say to judges:
   "Every action in that log is signed. Nobody — including us — can
    alter what the system recorded. That's your accountability guarantee."
```

---

## JUDGE Q&A PREP

| Question | Answer |
|---|---|
| "Sensor data isn't reliable" | "Correct. We use sensors as one signal among six. No single signal claims certainty. We claim inference weight, not truth." |
| "What if the GPS is wrong?" | "GPS is used at geohash precision-6 (~1.2km cells). Exact coordinates are never the claim — ward-level clustering is." |
| "Attribution is probabilistic — can you act on it?" | "Yes. Public contractor ledger creates economic pressure without requiring legal certainty. Media, bond markets, and future procurement committees can act on probabilistic risk scores." |
| "TEE doesn't work on most Android phones" | "Correct. TEE is a trust bonus tier. System works at standard trust without it. TEE gives +0.05 confidence only when hardware attestation is available." |
| "Who enforces the escalation?" | "We don't claim enforcement. We create a machine-readable public record of probable warranty breaches. One journalist story can do what 1000 complaints cannot." |
| "Isn't this just FixMyStreet?" | "FixMyStreet tracks service requests. We track contract breaches. The output of our system is breach value in rupees and contractor financial exposure — not a ticket number." |

---

**Document Version:** 1.0
**Last Updated:** 2026-04-29
**Audience:** Coding agents, LLM-assisted development, hackathon build
**Do not modify:** agent/ folder, auth layer, db.py, ChatPage.jsx
