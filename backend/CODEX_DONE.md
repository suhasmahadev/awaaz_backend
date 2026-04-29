# CODEX_DONE.md — AWAAZ-PROOF Final Status

## ANTIGRAVITY FINAL COMPLETIONS

### Mission A — Audit + Fix
- [x] `utils/confidence.py` — REWRITTEN: added `calculate_confidence()`, `ConfidenceBreakdown`, `ESCALATION_THRESHOLD`. Assertion guard verified: positive sum = 1.10
- [x] `utils/hashing.py` — REWRITTEN: `ANON_SALT` raises RuntimeError if missing. Added `generate_audit_signature()` and `verify_audit_signature()` (constant-time `hmac.compare_digest`)
- [x] `utils/tee.py` — VERIFIED: sign/verify/get_trust_tier all correct. `ENCLAVE_KEY` logs critical if missing
- [x] `utils/geo.py` — REWRITTEN: pure-Python geohash encoder (no binary deps). Verified `(12.9716, 77.5946, 7) → 'tdr1v9q'`
- [x] `services/service.py` — REWRITTEN: correct method names, live failure_score recompute, all 5 confidence chain links commented and verified

### Mission B — Anonymous Identity Chain
- [x] `POST /auth/anon` validates fingerprint (non-empty, ≤500 chars), returns only `anon_id`, never fingerprint
- [x] `POST /complaints/new` verifies anon_id exists in DB before insert → 404 if not found
- [x] `POST /complaints/{id}/vote` → 403 for self-vote, 409 for duplicate, flags reporter if >20 votes/hour

### Mission C — Confidence Chain Integrity (all 5 links verified in code)
- [x] Link 1: score=0.30, signals={single_report: 0.30}, status='unverified'
- [x] Link 2: photo_attached → 0.45, status='low_confidence'
- [x] Link 3: multi_reporter_48h → 0.65, status='medium_confidence'
- [x] Link 4: community_vote_net_5 → 0.75, auto_escalate=True, status='high_confidence'
- [x] Link 5: _update_contractor_on_breach() called once (guarded by prev_score < ESCALATION_THRESHOLD)

```
python3 -c "from utils.confidence import calculate_confidence; ..."
Link 1: 0.3  unverified
Link 2: 0.45 low
Link 3: 0.65 medium
Link 4: 0.75 high auto_escalate: True
ALL LINKS PASS ✓
```

### Mission D — Repo Method Completeness
All methods now present with correct parameterised SQL:
- [x] `count_complaints_by_geohash_48h` — COUNT(DISTINCT anon_id), excludes system_sensor_agent
- [x] `count_complaints_by_geohash_30d` — ADDED (was missing)
- [x] `get_net_vote_count` — COALESCE(SUM(CASE...), 0)
- [x] `has_voted` — EXISTS query
- [x] `is_own_complaint` — ADDED (was missing), used for self-vote 403
- [x] `count_votes_by_anon_last_hour` — anti-gaming check
- [x] `find_nearest_asset` — ANY($1::text[]) corrected
- [x] `list_complaints_by_area` — ADDED (was missing), LIKE prefix match
- [x] `count_active_breaches_by_contractor` — ADDED (was missing), JOIN complaints→contracts
- [x] `count_active_contracts_by_contractor` — ADDED (was missing)
- [x] `get_breach_history_by_contractor` — ADDED (was missing)
- [x] `get_evidence_by_id` — ADDED (was missing)
- [x] `get_overview_stats` — ADDED (renamed from admin_overview, alias kept)
- [x] `flag_anon_reporter` — ADDED (anti-gaming, sets trust_tier='flagged')
- [x] `list_all_complaints` — ADDED city param via JOIN to assets

### Mission E — Contractor Ledger
- [x] failure_score LIVE recomputed: `min(breach_count / max(active_contracts, 1), 1.0)`
- [x] NOT read from stale DB column — computed fresh per request in `service.get_ledger()`
- [x] `/ledger/feed` returns `total_breach_exposure_inr`, sorted by breach value DESC

### Mission F — Evidence Hashing
- [x] `POST /evidence/submit`: bytes read → SHA-256 hash → file stored → TEE sign if requested
- [x] `POST /verify/before-after`: 422 if before/after missing, honest 503 if CLIP unavailable, audit log for both outcomes

### Mission G — Security Headers + Rate Limiting
- [x] CORS tightened to `localhost:5173`, `localhost:5174` only
- [x] Rate limiter middleware: `/auth/anon` (10/min), `/complaints/new` (5/min) per IP
- [x] Rate limiter is in-memory (honest — documented not Redis, resets on restart)

### Mission H — Routers Cleaned
- [x] `routers/verification.py` — REWRITTEN: no stale imports, uses Request injection
- [x] `routers/complaints.py` — REWRITTEN: correct method names, proper HTTP errors
- [x] `routers/admin.py` — REWRITTEN: Request injection, admin auth guard
- [x] `main.py` — CLEANED: removed dead `sensor_router` import/include

---

## WHAT STILL NEEDS DOING (before demo)
| Item | Priority | Notes |
|------|----------|-------|
| Register admin user | HIGH | `POST /auth/register {email,password,role:"admin"}` |
| Set ANON_SALT + ENCLAVE_KEY in .env | HIGH | Server starts but /auth/anon raises without ANON_SALT |
| CLIP install (optional) | MEDIUM | `pip install git+https://github.com/openai/CLIP.git torch` — /verify/before-after returns honest 503 without it |
| Frontend react-router-dom | LOW | `npm install react-router-dom` in frontend/ |

---

## UNIT TEST RESULTS (verified locally)
```
utils/confidence.py: ALL LINKS PASS (0.30 / 0.45 / 0.65 / 0.75)
utils/hashing.py:    generate_anon_id, hash_evidence_payload, generate_audit_signature, verify_audit_signature — ALL PASS
utils/tee.py:        sign_evidence_payload, verify_evidence_signature — ALL PASS
utils/geo.py:        coords_to_geohash(12.9716, 77.5946, 7) == 'tdr1v9q' — PASS
```
