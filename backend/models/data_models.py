"""Domain Pydantic models for AWAAZ-PROOF."""
from pydantic import BaseModel
from typing import Optional


class User(BaseModel):
    id: Optional[str] = None
    name: str
    email: str
    password_hash: Optional[str] = None
    role: str = "citizen"  # citizen | admin | moderator | faculty


class AnonReporter(BaseModel):
    anon_id: str
    trust_tier: str = "standard"
    reports_submitted: int = 0
    reports_corroborated: int = 0
    reputation_score: float = 0.5
    created_at: Optional[str] = None


class Asset(BaseModel):
    id: Optional[str] = None
    asset_type: str
    geohash: str
    lat: float
    lng: float
    ward_id: Optional[str] = None
    city: str = "Bengaluru"


class Contractor(BaseModel):
    id: Optional[str] = None
    name: str
    registration_no: Optional[str] = None
    city: str = "Bengaluru"
    active_contracts: int = 0
    total_breach_value_inr: int = 0
    failure_score: float = 0.0


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
    media_url: Optional[str] = None
    report_count: int = 1
    reporters: list[str] = []
    cluster_id: Optional[str] = None
    contractor: Optional[dict] = None


class Evidence(BaseModel):
    id: Optional[str] = None
    complaint_id: str
    anon_id: str
    evidence_type: str
    file_path: Optional[str] = None
    state_hash: Optional[str] = None
    state_type: str  # before | after | support
    lat: float
    lng: float
    timestamp: str
    tee_signed: bool = False
    sensor_data: Optional[dict] = None


class Vote(BaseModel):
    id: Optional[str] = None
    complaint_id: str
    anon_id: str
    vote_type: str  # corroborate | dispute


class SensorCluster(BaseModel):
    id: Optional[str] = None
    geohash: str
    event_type: str
    device_count: int = 1
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    auto_complaint_raised: bool = False
    complaint_id: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    role: str = "citizen"
    anon_id: Optional[str] = None
    lat: float = 12.9716
    lng: float = 77.5946
    radius_km: float = 2.0
    complaint_id: Optional[str] = None
    vote_type: Optional[str] = None
    city: str = "Bengaluru"
