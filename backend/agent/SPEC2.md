# CODEX — ADMIN PANEL COMPLETE BUILD

## FIXED CREDENTIALS
```
email: admin@gmail.com
password: admin123
role: admin
```
Seed this user in `main.py` lifespan (upsert, don't duplicate):
```python
admin_exists = await pool.fetchval("SELECT id FROM users WHERE email=$1", "admin@gmail.com")
if not admin_exists:
    from auth_security import hash_password
    await pool.execute("""
        INSERT INTO users (id, name, email, password_hash, role)
        VALUES ($1,'Admin','admin@gmail.com',$2,'admin')
    """, "usr_admin_001", hash_password("admin123"))
```

---

## BACKEND — 3 NEW TABLES (add to lifespan)

```sql
CREATE TABLE IF NOT EXISTS complaint_assignments (
    id              TEXT PRIMARY KEY,
    complaint_id    TEXT REFERENCES complaints(id),
    contractor_id   TEXT,          -- org_profiles.user_id
    contractor_name TEXT,
    assigned_by     TEXT,          -- admin user_id
    assigned_at     TIMESTAMPTZ DEFAULT NOW(),
    due_date        DATE,
    status          TEXT DEFAULT 'assigned'
                    CHECK (status IN ('assigned','in_progress','resolved','rejected'))
);

CREATE TABLE IF NOT EXISTS ai_summaries (
    id              TEXT PRIMARY KEY,
    complaint_id    TEXT REFERENCES complaints(id) UNIQUE,
    summary         TEXT,
    risk_level      TEXT CHECK (risk_level IN ('critical','high','medium','low')),
    risk_reason     TEXT,
    recommended_action TEXT,
    generated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ngo_requests already exists — add type column if missing:
ALTER TABLE ngo_requests ADD COLUMN IF NOT EXISTS
    org_type TEXT DEFAULT 'ngo';
```

## BACKEND — NEW ENDPOINTS (new file `routers/admin_ops.py`)

Mount at prefix `/admin` in main.py.

```python
# All endpoints require admin JWT

# GET /admin/dashboard
# Returns everything for admin home in one call:
{
  "stats": {
    "total_complaints": int,
    "high_confidence": int,       -- confidence >= 0.75
    "critical_risk": int,         -- ai_summaries.risk_level = 'critical'
    "pending_ngo_requests": int,
    "resolved_this_week": int,
    "total_breach_value_inr": int
  },
  "top_risk_complaints": [],      -- top 5 by risk_level + confidence
  "pending_assignments": [],      -- complaints with no assignment
  "recent_resolved": []
}

# GET /admin/complaints?status=&risk=&assigned=true|false
# Full complaint list with filters + ai_summary + assignment joined

# POST /admin/complaints/{id}/summarise
# Calls Gemini to generate AI summary + risk assessment
# Stores in ai_summaries table
# Body: {} (no input needed — reads complaint from DB)
# Returns: {summary, risk_level, risk_reason, recommended_action}

# POST /admin/complaints/{id}/assign
# Body: {contractor_user_id, due_date}
# Inserts complaint_assignments record
# Updates complaint status to 'assigned'
# Returns: assignment record

# PATCH /admin/complaints/{id}/resolve
# Body: {resolved: true|false, admin_note}
# Updates complaint status to 'resolved' or 'disputed'

# GET /admin/ngo-requests
# Returns all with org_name, org_type, complaint details, status

# PATCH /admin/ngo-requests/{id}/approve
# Sets status='approved'
# If contractor request: reveal complaint full address + ward
# Returns: {approved: true, complaint_details}

# PATCH /admin/ngo-requests/{id}/reject
# Body: {reason}
# Sets status='rejected', stores reason in admin_note

# GET /admin/contractors
# All org_profiles WHERE org_type='contractor' + their assignment counts

# GET /admin/schedule
# Returns complaint_assignments with due_date sorted ASC
# Groups by: overdue | due_today | upcoming
```

## AI SUMMARISATION (inside `POST /admin/complaints/{id}/summarise`)

```python
import google.generativeai as genai, os, json
genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
model = genai.GenerativeModel("gemini-2.0-flash")

prompt = f"""
Analyze this civic complaint and return ONLY JSON, no markdown.

Complaint type: {complaint['complaint_type']}
Description: {complaint['description']}
Confidence score: {complaint['confidence_score']}
Warranty breach: {complaint['warranty_breach']}
Breach value INR: {complaint['breach_value_inr']}
Vote count: {complaint['vote_count']}
Created: {complaint['created_at']}

Return:
{{
  "summary": "2-sentence plain English summary for admin",
  "risk_level": "critical|high|medium|low",
  "risk_reason": "one line: why this risk level",
  "recommended_action": "specific action admin should take"
}}

Risk guide:
- critical: warranty breach + injury signal + confidence>=0.75
- high: warranty breach OR confidence>=0.75
- medium: confidence>=0.55
- low: everything else
"""
resp = model.generate_content(prompt)
raw = resp.text.strip().strip("```json").strip("```").strip()
result = json.loads(raw)
# Store in ai_summaries, return result
```

---

## FRONTEND — `AdminPanel.jsx` FULL REWRITE

Admin has NO chat agent. Replace completely.

### Layout: sidebar + main content
```
┌──────────┬────────────────────────────────────────┐
│ AWAAZ    │  [nav tabs across top]                  │
│ ADMIN    │                                         │
│          │  [content area]                         │
│ 📊 Home  │                                         │
│ 🗺 Map   │                                         │
│ 🗣 Comm  │                                         │
│ 📋 Compl │                                         │
│ 🏗 Sched │                                         │
│ 🤝 NGO   │                                         │
│ 📜 Audit │                                         │
└──────────┴────────────────────────────────────────┘
```

### TAB 1 — Home (Dashboard)
```jsx
// Fetch GET /admin/dashboard on mount
// Stats row: 6 cards
[Total Complaints] [High Confidence] [Critical Risk] [Pending NGO] [Resolved Week] [Breach ₹]

// Top Risk Complaints table (top 5)
// Columns: Type | Ward | Risk | Confidence | Warranty | Action
// Risk badge: critical=red, high=orange, medium=blue, low=grey
// Action: [Summarise AI] [Assign] [Resolve]

// [Summarise AI] button:
// POST /admin/complaints/{id}/summarise
// Shows result inline below row:
//   "Summary: Road surface collapsed 8 months after completion..."
//   "Risk: CRITICAL — warranty breach + injury signal"
//   "Recommended: Issue notice to contractor within 48h"

// Pending Assignments (no contractor yet)
// List of complaints with [Assign Contractor] button
```

### TAB 2 — Map
```jsx
// Reuse MapView component exactly
// Admin sees same map — no changes needed
import MapView from "./MapView"
return <MapView />
```

### TAB 3 — Community
```jsx
// Reuse CommunityFeed component exactly
import CommunityFeed from "./CommunityFeed"
return <CommunityFeed adminMode={true} />
// In CommunityFeed: if adminMode, show [Mark Resolved] button on each card
```

### TAB 4 — Complaints (full list)
```jsx
// Fetch GET /admin/complaints
// Filters: status dropdown | risk dropdown | assigned toggle
// Table columns:
// ID(short) | Type | Confidence | Risk | Assigned To | Status | Actions

// Actions per row:
// [🤖 AI Summary] — calls summarise endpoint, shows modal
// [👷 Assign]     — opens contractor picker modal
// [✓ Resolve]     — PATCH resolve with toggle
// [✗ Dispute]     — PATCH resolve with resolved:false

// Assign contractor modal:
// GET /admin/contractors → dropdown list
// Select contractor + date picker for due_date
// POST /admin/complaints/{id}/assign
```

### TAB 5 — Schedule
```jsx
// Fetch GET /admin/schedule
// Three sections: OVERDUE (red) | DUE TODAY (amber) | UPCOMING (green)
// Each item: complaint type | ward | contractor name | due date | status
// [Mark Resolved] button on each
// Visual: timeline-style list, colour coded by urgency
```

### TAB 6 — NGO / Contractor Requests
```jsx
// Fetch GET /admin/ngo-requests
// Two sub-tabs: [NGO Requests] [Contractor Connect Requests]
// Filter by org_type

// Each request card:
// Org name | Type (NGO/Contractor) | Complaint ID | Message | Submitted
// [Approve] green button → PATCH approve → show success, refresh
// [Reject]  red button   → prompt for reason → PATCH reject

// After approve: show "Details shared" badge on that row
// Approved contractor requests: show complaint ward + admin contact
```

### TAB 7 — Audit Log
```jsx
// Fetch GET /admin/audit-log
// Scrollable table: action | entity | actor | timestamp | sig_valid
// sig_valid: green ✓ or red ✗
```

---

## ADMIN ROUTE GUARD (`frontend/src/pages/AdminPanel.jsx`)

```jsx
// On mount: check localStorage.getItem('role') === 'admin'
// If not admin → redirect to '/'
// If not logged in → redirect to '/ngo-login'

useEffect(() => {
  const role  = localStorage.getItem('role')
  const token = localStorage.getItem('token')
  if (!token) { navigate('/ngo-login'); return }
  if (role !== 'admin') { navigate('/'); return }
}, [])
```

---

## ROUTING UPDATE (`main.jsx`)

Admin goes directly to `/admin` — no chat. Add to nav bar:
```jsx
// Show admin link only if role==='admin'
// Admin NavBar has no footer — uses sidebar instead
```

---

## MISSIONS IN ORDER

1. Seed admin user in lifespan (upsert)
2. Add 3 tables: complaint_assignments, ai_summaries, alter ngo_requests
3. Write `routers/admin_ops.py` with all 9 endpoints
4. Wire admin_ops router in main.py: `app.include_router(admin_ops_router, prefix="/admin", tags=["Admin Ops"])`
5. Rewrite `AdminPanel.jsx` with sidebar + 7 tabs
6. AI summarise button — calls endpoint, renders result inline
7. Assign contractor flow — modal with contractor list + due date
8. Schedule tab — overdue/today/upcoming groups
9. NGO tab — approve/reject with org_type filter
10. Admin route guard — redirect non-admin away

## RULES
- Admin has zero chat agent — if role=admin, /agent/chat still works as API but no UI for it
- MapView and CommunityFeed reused as-is — no copy-paste
- All admin fetches include: `headers: {"Authorization": "Bearer " + localStorage.getItem('token')}`
- AI summarise: if Gemini fails, store fallback `{summary: complaint.description, risk_level: "medium", risk_reason: "Manual review needed", recommended_action: "Inspect site"}`
- Due date picker: plain `<input type="date">` — no library