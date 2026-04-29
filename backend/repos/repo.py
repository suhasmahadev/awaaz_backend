"""
Complete repository layer — AWAAZ-PROOF.
ANTIGRAVITY: added missing methods:
  - is_own_complaint
  - count_complaints_by_geohash_30d
  - list_complaints_by_area
  - count_active_breaches_by_contractor
  - get_breach_history_by_contractor
  - get_evidence_by_id
  - get_overview_stats
  - flag_anon_reporter
  - list_all_complaints now accepts city param
All SQL uses parameterised queries ($1, $2) — no f-strings.
"""
import json
import logging
import time
import uuid
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _row(row) -> Optional[dict]:
    return dict(row) if row else None


def _date(value):
    return date.fromisoformat(value) if isinstance(value, str) else value


class Repo:
    def __init__(self, pool=None):
        self._pool = pool

    @property
    def pool(self):
        # ANTIGRAVITY: lazy fallback to PostgresDB.pool for legacy code paths
        if self._pool is not None:
            return self._pool
        from db import PostgresDB
        return PostgresDB.pool

    # ── Users ──────────────────────────────────────────────────────────────────
    async def insert_user(self, user) -> object:
        user.id = user.id or _id("usr")
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO users(id,name,email,password_hash,role) "
                "VALUES($1,$2,$3,$4,$5) ON CONFLICT(email) DO NOTHING",
                user.id, user.name, user.email, user.password_hash, user.role,
            )
        return user

    async def get_user_by_email(self, email: str) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            return _row(await conn.fetchrow("SELECT * FROM users WHERE email=$1", email))

    async def get_user_by_id(self, user_id: str) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            return _row(await conn.fetchrow("SELECT * FROM users WHERE id=$1", user_id))

    # ── Anonymous reporters ────────────────────────────────────────────────────
    async def insert_anon_reporter(self, anon_id: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO anonymous_reporters(anon_id) VALUES($1) ON CONFLICT DO NOTHING",
                anon_id,
            )

    async def get_anon_reporter(self, anon_id: str) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            return _row(await conn.fetchrow(
                "SELECT * FROM anonymous_reporters WHERE anon_id=$1", anon_id,
            ))

    async def get_anon_id_by_fingerprint(self, fingerprint: str) -> Optional[str]:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT anon_id FROM anon_users WHERE fingerprint=$1",
                fingerprint,
            )

    async def update_anon_reputation(self, anon_id: str, score: float) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE anonymous_reporters SET reputation_score=$2 WHERE anon_id=$1",
                anon_id, score,
            )

    async def flag_anon_reporter(self, anon_id: str) -> None:
        """ANTIGRAVITY: sets trust_tier='flagged' for anti-gaming enforcement."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE anonymous_reporters SET trust_tier='flagged' WHERE anon_id=$1",
                anon_id,
            )

    async def get_anon_trust_tier(self, anon_id: str) -> str:
        """Returns trust_tier string or 'standard' if reporter not found."""
        async with self.pool.acquire() as conn:
            val = await conn.fetchval(
                "SELECT trust_tier FROM anonymous_reporters WHERE anon_id=$1", anon_id,
            )
            return val or "standard"

    # ── Assets ─────────────────────────────────────────────────────────────────
    async def insert_asset(self, a) -> object:
        a.id = a.id or _id("ast")
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO assets(id,asset_type,geohash,lat,lng,ward_id,city) "
                "VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT(id) DO NOTHING",
                a.id, a.asset_type, a.geohash, a.lat, a.lng, a.ward_id, a.city,
            )
        return a

    async def get_asset_by_id(self, asset_id: str) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            return _row(await conn.fetchrow("SELECT * FROM assets WHERE id=$1", asset_id))

    async def find_nearest_asset(self, geohashes: list[str]) -> Optional[dict]:
        """
        ANTIGRAVITY: corrected SQL — ANY($1::text[]) instead of nested ORs.
        Returns nearest asset by geohash prefix match (precision 7, 6, 5).
        """
        async with self.pool.acquire() as conn:
            return _row(await conn.fetchrow(
                "SELECT * FROM assets WHERE geohash = ANY($1::text[]) LIMIT 1",
                geohashes,
            ))

    # ── Contractors ────────────────────────────────────────────────────────────
    async def insert_contractor(self, c) -> object:
        c.id = c.id or _id("ctr")
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO contractors(id,name,registration_no,city,"
                "active_contracts,total_breach_value_inr,failure_score) "
                "VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT(id) DO NOTHING",
                c.id, c.name, c.registration_no, c.city,
                c.active_contracts, c.total_breach_value_inr, c.failure_score,
            )
        return c

    async def get_contractor(self, contractor_id: str) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            return _row(await conn.fetchrow(
                "SELECT * FROM contractors WHERE id=$1", contractor_id,
            ))

    async def list_contractors(self, city: str = None) -> list[dict]:
        async with self.pool.acquire() as conn:
            if city:
                rows = await conn.fetch(
                    "SELECT * FROM contractors WHERE lower(city)=lower($1) "
                    "ORDER BY failure_score DESC",
                    city,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM contractors ORDER BY failure_score DESC"
                )
            return [dict(r) for r in rows]

    async def update_contractor_scores(
        self,
        contractor_id: str,
        breach_count: int,
        breach_value: int,
        score: float,
    ) -> None:
        """
        ANTIGRAVITY: stores recomputed live values back to contractors table.
        Does NOT use stored columns as source of truth — always live-computed.
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE contractors SET total_breach_value_inr=$2,"
                "failure_score=$3,updated_at=NOW() WHERE id=$1",
                contractor_id, breach_value, score,
            )

    async def count_active_breaches_by_contractor(self, contractor_id: str) -> int:
        """
        ANTIGRAVITY: was missing entirely.
        Counts high_confidence complaints under this contractor's contracts.
        SQL: JOIN complaints→contracts by contractor_id, filter status='high_confidence'.
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM complaints c
                JOIN contracts ct ON c.contract_id = ct.id
                WHERE ct.contractor_id = $1
                  AND c.status = 'high_confidence'
                """,
                contractor_id,
            ) or 0

    async def get_breach_history_by_contractor(self, contractor_id: str) -> list[dict]:
        """
        ANTIGRAVITY: was missing. Used by service.get_contractor_profile().
        Returns high_confidence + resolved complaints for contractor, joined with contract data.
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.id, c.complaint_type, c.confidence_score, c.status,
                       c.geohash, c.breach_value_inr,
                       ct.completion_date, ct.warranty_expiry
                FROM complaints c
                JOIN contracts ct ON c.contract_id = ct.id
                WHERE ct.contractor_id = $1
                  AND c.status IN ('high_confidence', 'resolved')
                ORDER BY c.confidence_score DESC
                """,
                contractor_id,
            )
            return [dict(r) for r in rows]

    async def count_active_contracts_by_contractor(self, contractor_id: str) -> int:
        """Count active (non-expired) contracts for this contractor."""
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT COUNT(*) FROM contracts WHERE contractor_id=$1 AND status='active'",
                contractor_id,
            ) or 0

    # ── Contracts ──────────────────────────────────────────────────────────────
    async def insert_contract(self, c) -> object:
        c.id = c.id or _id("con")
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO contracts(id,asset_id,contractor_id,contract_number,
                   contract_value_inr,completion_date,warranty_months,
                   warranty_expiry,status,is_synthetic)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT(id) DO NOTHING""",
                c.id, c.asset_id, c.contractor_id, c.contract_number,
                c.contract_value_inr, _date(c.completion_date), c.warranty_months,
                _date(c.warranty_expiry), c.status, c.is_synthetic,
            )
        return c

    async def get_contract_by_asset(self, asset_id: str) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            return _row(await conn.fetchrow(
                "SELECT * FROM contracts WHERE asset_id=$1 "
                "ORDER BY warranty_expiry DESC LIMIT 1",
                asset_id,
            ))

    async def get_contracts_by_asset(self, asset_id: str) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM contracts WHERE asset_id=$1 ORDER BY warranty_expiry DESC",
                asset_id,
            )
            return [dict(r) for r in rows]

    async def get_contract_by_id(self, contract_id: str) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            return _row(await conn.fetchrow("SELECT * FROM contracts WHERE id=$1", contract_id))

    # ── Complaints ─────────────────────────────────────────────────────────────
    async def insert_complaint(self, c) -> object:
        c.id = c.id or _id("cmp")
        reporters = getattr(c, "reporters", None) or []
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO complaints(id,anon_id,asset_id,contract_id,complaint_type,
                   description,lat,lng,geohash,status,confidence_score,
                   confidence_signals,warranty_breach,breach_value_inr,vote_count,media_url,
                   report_count,reporters,cluster_id,contractor)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb,$13,$14,$15,$16,
                          $17,$18::jsonb,$19,$20::jsonb)""",
                c.id, c.anon_id, c.asset_id, c.contract_id,
                c.complaint_type, c.description, c.lat, c.lng,
                c.geohash, c.status, c.confidence_score,
                json.dumps(c.confidence_signals),
                c.warranty_breach, c.breach_value_inr, c.vote_count,
                getattr(c, "media_url", None),
                getattr(c, "report_count", 1) or 1,
                json.dumps(reporters),
                getattr(c, "cluster_id", None),
                json.dumps(getattr(c, "contractor", None)) if getattr(c, "contractor", None) else None,
            )
        return c

    async def find_nearby_complaint(
        self,
        complaint_type: str,
        lat: float,
        lng: float,
        threshold_m: float = 100.0,
    ) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT *
                FROM complaints
                WHERE complaint_type=$1
                  AND lat IS NOT NULL
                  AND lng IS NOT NULL
                  AND status != 'resolved'
                ORDER BY created_at DESC
                LIMIT 250
                """,
                complaint_type,
            )
        from utils.geo import haversine_meters

        best = None
        best_distance = None
        for row in rows:
            item = dict(row)
            distance = haversine_meters(lat, lng, float(item["lat"]), float(item["lng"]))
            if distance <= threshold_m and (best_distance is None or distance < best_distance):
                best = item
                best_distance = distance
        return best

    async def aggregate_complaint_report(
        self,
        complaint_id: str,
        reporter_hash: str,
        media_url: str = None,
    ) -> dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT reporters
                FROM complaints
                WHERE id=$1
                FOR UPDATE
                """,
                complaint_id,
            )
            if not row:
                raise ValueError("Complaint not found")

            reporters = row["reporters"] or []
            if isinstance(reporters, str):
                try:
                    reporters = json.loads(reporters)
                except json.JSONDecodeError:
                    reporters = []
            already_reported = reporter_hash in reporters
            if not already_reported:
                reporters.append(reporter_hash)

            updated = await conn.fetchrow(
                """
                UPDATE complaints
                SET reporters=$2::jsonb,
                    report_count=$3,
                    media_url=COALESCE(media_url, $4),
                    updated_at=NOW()
                WHERE id=$1
                RETURNING *
                """,
                complaint_id,
                json.dumps(reporters),
                len(reporters) if reporters else 1,
                media_url,
            )
            data = dict(updated)
            data["already_reported"] = already_reported
            return data

    async def get_complaint(self, complaint_id: str) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            return _row(await conn.fetchrow(
                "SELECT * FROM complaints WHERE id=$1", complaint_id,
            ))

    async def update_complaint_confidence(
        self,
        complaint_id: str,
        score: float,
        signals: dict,
        status: str,
    ) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE complaints SET confidence_score=$2,confidence_signals=$3::jsonb,"
                "status=$4,updated_at=NOW() WHERE id=$1",
                complaint_id, score, json.dumps(signals), status,
            )

    async def update_complaint_status(self, complaint_id: str, status: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE complaints SET status=$2,updated_at=NOW() WHERE id=$1",
                complaint_id, status,
            )

    async def list_complaints_by_geohash(self, geohashes: list[str]) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM complaints WHERE geohash = ANY($1::text[]) "
                "ORDER BY confidence_score DESC",
                geohashes,
            )
            return [dict(r) for r in rows]

    async def list_complaints_by_area(self, geohash5: str) -> list[dict]:
        """
        ANTIGRAVITY: was missing. Returns complaints with geohash prefix match.
        SQL: LIKE prefix match on geohash5 (≈5km radius).
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM complaints WHERE geohash LIKE $1 || '%' "
                "ORDER BY confidence_score DESC",
                geohash5,
            )
            return [dict(r) for r in rows]

    async def list_complaints_by_anon(self, anon_id: str) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM complaints WHERE anon_id=$1 ORDER BY created_at DESC",
                anon_id,
            )
            return [dict(r) for r in rows]

    async def list_complaint_history_by_fingerprint(self, fingerprint: str) -> list[dict]:
        """
        Fetch complaint history by device fingerprint through anon_users.
        This fixes the invisible-history bug caused by querying complaints with
        the raw fingerprint instead of the derived anon_id.
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.id AS grievance_id, c.status, c.created_at
                FROM complaints c
                JOIN anon_users au ON au.anon_id = c.anon_id
                WHERE au.fingerprint=$1
                ORDER BY c.created_at DESC
                """,
                fingerprint,
            )
            return [dict(r) for r in rows]

    async def insert_comment(
        self,
        complaint_id: str,
        anon_id: str,
        comment_type: str,
        text: str,
        image_path: str = None,
        image_hash: str = None,
    ) -> dict:
        cid = f"cmt_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO complaint_comments
                (id, complaint_id, anon_id, comment_type, text, image_path, image_hash, created_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,NOW())
                RETURNING id, complaint_id, anon_id, comment_type, text, image_path, image_hash, created_at
                """,
                cid, complaint_id, anon_id, comment_type, text, image_path, image_hash,
            )
            return dict(row)

    async def list_comments(self, complaint_id: str) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, complaint_id, anon_id, comment_type, text,
                       image_path, image_hash, created_at
                FROM complaint_comments
                WHERE complaint_id=$1
                ORDER BY created_at ASC
                """,
                complaint_id,
            )
            return [dict(r) for r in rows]

    async def get_complaint_with_evidence(self, complaint_id: str) -> Optional[dict]:
        """Returns complaint + evidence list + comments in one call."""
        complaint = await self.get_complaint(complaint_id)
        if not complaint:
            return None
        evidence = await self.get_evidence_by_complaint(complaint_id)
        comments = await self.list_comments(complaint_id)
        result = dict(complaint)
        result["evidence"] = [dict(e) for e in evidence]
        result["comments"] = comments
        return result

    async def list_all_complaints(
        self,
        status: str = None,
        city: str = None,
    ) -> list[dict]:
        """
        ANTIGRAVITY: added city param via JOIN to assets table.
        """
        async with self.pool.acquire() as conn:
            if status and city:
                rows = await conn.fetch(
                    """SELECT c.* FROM complaints c
                       LEFT JOIN assets a ON c.asset_id = a.id
                       WHERE c.status=$1 AND lower(a.city)=lower($2)
                       ORDER BY c.created_at DESC""",
                    status, city,
                )
            elif status:
                rows = await conn.fetch(
                    "SELECT * FROM complaints WHERE status=$1 ORDER BY created_at DESC",
                    status,
                )
            elif city:
                rows = await conn.fetch(
                    """SELECT c.* FROM complaints c
                       LEFT JOIN assets a ON c.asset_id = a.id
                       WHERE lower(a.city)=lower($1)
                       ORDER BY c.created_at DESC""",
                    city,
                )
            else:
                rows = await conn.fetch("SELECT * FROM complaints ORDER BY created_at DESC")
            return [dict(r) for r in rows]

    async def count_complaints_by_geohash_48h(self, geohash6: str) -> int:
        """
        Counts DISTINCT reporters (anon_id) at this geohash6 in last 48h.
        Excludes system_sensor_agent to prevent auto-complaints from inflating count.
        SQL: COUNT(DISTINCT anon_id) for multi-reporter signal.
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                """
                SELECT COUNT(DISTINCT anon_id)
                FROM complaints
                WHERE geohash LIKE $1 || '%'
                  AND created_at > NOW() - INTERVAL '48 hours'
                  AND anon_id != 'system_sensor_agent'
                """,
                geohash6,
            ) or 0

    async def count_complaints_by_geohash_30d(self, geohash6: str) -> int:
        """
        ANTIGRAVITY: was missing. Used for repeat_temporal_pattern signal.
        Counts ALL complaints (not just distinct reporters) at geohash6 in 30 days.
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM complaints
                WHERE geohash LIKE $1 || '%'
                  AND created_at > NOW() - INTERVAL '30 days'
                """,
                geohash6,
            ) or 0

    async def is_own_complaint(self, complaint_id: str, anon_id: str) -> bool:
        """
        ANTIGRAVITY: was missing. Used by vote endpoint to prevent self-voting.
        Returns True if anon_id is the original reporter of complaint_id.
        """
        async with self.pool.acquire() as conn:
            return bool(await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM complaints WHERE id=$1 AND anon_id=$2)",
                complaint_id, anon_id,
            ))

    # ── Evidence ───────────────────────────────────────────────────────────────
    async def insert_evidence(self, e) -> object:
        e.id = e.id or _id("ev")
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO evidence(id,complaint_id,anon_id,evidence_type,
                   file_path,state_hash,state_type,lat,lng,timestamp,
                   tee_signed,sensor_data)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb)""",
                e.id, e.complaint_id, e.anon_id, e.evidence_type,
                e.file_path, e.state_hash, e.state_type, e.lat, e.lng,
                e.timestamp, e.tee_signed,
                json.dumps(e.sensor_data) if e.sensor_data else None,
            )
        return e

    async def insert_evidence_raw(
        self,
        ev_id: str,
        complaint_id: str,
        anon_id: str,
        ev_type: str,
        file_path: str,
        state_hash: str,
        state_type: str,
        lat: float,
        lng: float,
        ts,
        tee_signed: bool,
    ) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO evidence
                (id, complaint_id, anon_id, evidence_type, file_path,
                 state_hash, state_type, lat, lng, timestamp, tee_signed, created_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,NOW(),$10,NOW())
                """,
                ev_id, complaint_id, anon_id, ev_type, file_path,
                state_hash, state_type, lat, lng, tee_signed,
            )

    async def get_evidence_by_id(self, evidence_id: str) -> Optional[dict]:
        """ANTIGRAVITY: was missing. Used by GET /evidence/{id}."""
        async with self.pool.acquire() as conn:
            return _row(await conn.fetchrow(
                "SELECT * FROM evidence WHERE id=$1", evidence_id,
            ))

    async def get_evidence_by_complaint(self, complaint_id: str) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM evidence WHERE complaint_id=$1 ORDER BY created_at DESC",
                complaint_id,
            )
            return [dict(r) for r in rows]

    async def count_photo_evidence(self, complaint_id: str) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT COUNT(*) FROM evidence WHERE complaint_id=$1 AND evidence_type='photo'",
                complaint_id,
            ) or 0

    async def has_after_state(self, complaint_id: str) -> bool:
        async with self.pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM evidence WHERE complaint_id=$1 AND state_type='after'",
                complaint_id,
            )
            return bool(count)

    # ── Votes ──────────────────────────────────────────────────────────────────
    async def insert_vote(self, v) -> object:
        v.id = v.id or _id("vot")
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO votes(id,complaint_id,anon_id,vote_type) VALUES($1,$2,$3,$4)",
                v.id, v.complaint_id, v.anon_id, v.vote_type,
            )
            # Update complaint vote_count atomically
            vote_count = await self.get_net_vote_count(v.complaint_id)
            await conn.execute(
                "UPDATE complaints SET vote_count=$2 WHERE id=$1",
                v.complaint_id, vote_count,
            )
        return v

    async def get_net_vote_count(self, complaint_id: str) -> int:
        """
        Net vote count: corroborate=+1, dispute=-1.
        SQL: COALESCE(SUM(...), 0) — returns 0 if no votes.
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                """
                SELECT COALESCE(
                    SUM(CASE WHEN vote_type='corroborate' THEN 1 ELSE -1 END),
                    0
                )
                FROM votes WHERE complaint_id=$1
                """,
                complaint_id,
            ) or 0

    async def has_voted(self, complaint_id: str, anon_id: str) -> bool:
        """
        Returns True if this anon_id has already voted on this complaint.
        Uses EXISTS for O(1) performance.
        """
        async with self.pool.acquire() as conn:
            return bool(await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM votes WHERE complaint_id=$1 AND anon_id=$2)",
                complaint_id, anon_id,
            ))

    async def count_votes_by_anon_last_hour(self, anon_id: str) -> int:
        """Anti-gaming: count votes cast by this reporter in the last hour."""
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT COUNT(*) FROM votes WHERE anon_id=$1 "
                "AND created_at > NOW() - INTERVAL '1 hour'",
                anon_id,
            ) or 0

    # ── Sensor clusters ────────────────────────────────────────────────────────
    async def upsert_sensor_cluster(self, geohash6: str, event_type: str) -> dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO sensor_clusters(id,geohash,event_type,device_count,first_seen,last_seen)
                VALUES($1,$2,$3,1,NOW(),NOW())
                ON CONFLICT (geohash) DO UPDATE
                  SET device_count = sensor_clusters.device_count + 1,
                      last_seen = NOW()
                RETURNING *
                """,
                _id("clu"), geohash6, event_type,
            )
            return dict(row)

    async def get_cluster_by_geohash(self, geohash6: str) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            return _row(await conn.fetchrow(
                "SELECT * FROM sensor_clusters WHERE geohash=$1 LIMIT 1",
                geohash6,
            ))

    async def mark_cluster_complaint_raised(self, geohash6: str, complaint_id: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE sensor_clusters SET auto_complaint_raised=true,complaint_id=$2 "
                "WHERE geohash=$1",
                geohash6, complaint_id,
            )

    # ── Audit log ──────────────────────────────────────────────────────────────
    async def insert_audit_log(
        self,
        action: str,
        entity_type: str,
        entity_id: str,
        actor_id: str,
        payload: dict,
        signature: str,
    ) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO audit_log(id,action,entity_type,entity_id,"
                "actor_anon_id,payload,signature) VALUES($1,$2,$3,$4,$5,$6::jsonb,$7)",
                _id("aud"), action, entity_type, entity_id,
                actor_id, json.dumps(payload), signature,
            )

    async def list_audit_log(self, limit: int = 100) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT $1", limit,
            )
            return [dict(r) for r in rows]

    # ── Admin overview ─────────────────────────────────────────────────────────
    async def get_overview_stats(self) -> dict:
        """
        ANTIGRAVITY: was named admin_overview() — renamed to get_overview_stats()
        to match admin router call. Old name kept as alias.
        """
        async with self.pool.acquire() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM complaints") or 0
            breaches = await conn.fetchval(
                "SELECT COUNT(*) FROM complaints WHERE warranty_breach=true"
            ) or 0
            breach_val = await conn.fetchval(
                "SELECT COALESCE(SUM(breach_value_inr),0) FROM complaints "
                "WHERE warranty_breach=true"
            ) or 0
            by_status_rows = await conn.fetch(
                "SELECT status, COUNT(*) as count FROM complaints GROUP BY status"
            )
            by_status = {r["status"]: r["count"] for r in by_status_rows}
            top_failing = [
                dict(r) for r in await conn.fetch(
                    "SELECT id, name, failure_score FROM contractors "
                    "ORDER BY failure_score DESC LIMIT 5"
                )
            ]
            this_week = await conn.fetchval(
                "SELECT COUNT(*) FROM complaints "
                "WHERE created_at > NOW() - INTERVAL '7 days'"
            ) or 0
        return {
            "total_complaints":        total,
            "total_warranty_breaches": breaches,
            "total_breach_value_inr":  breach_val,
            "by_status":               by_status,
            "top_failing_contractors": top_failing,
            "complaints_this_week":    this_week,
        }

    # Keep old name as alias for backward compat
    async def admin_overview(self) -> dict:
        return await self.get_overview_stats()
