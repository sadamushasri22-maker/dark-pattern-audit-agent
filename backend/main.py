from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import random
import datetime

app = FastAPI(title="Dark Pattern Audit Agent API", version="0.1.0")

# ---------------------------------------------------------------------------
# CORS – allow the Vite dev server (and any origin during development)
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class AuditRequest(BaseModel):
    url: str
    options: Optional[dict] = {}

class ReviewRequest(BaseModel):
    audit_id: str
    feedback: Optional[str] = None

# ---------------------------------------------------------------------------
# Placeholder endpoints – no real logic yet
# ---------------------------------------------------------------------------

@app.post("/audit")
async def run_audit(request: AuditRequest):
    """
    Placeholder: Accepts a URL and returns fake audit findings.
    Real logic will use Hindsight to capture screenshots and Groq to analyse them.
    """
    fake_audit_id = f"audit_{random.randint(10000, 99999)}"
    return {
        "audit_id": fake_audit_id,
        "url": request.url,
        "status": "completed",
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "findings": [
            {
                "id": 1,
                "pattern": "Confirm-shaming",
                "severity": "high",
                "description": "The opt-out button uses guilt-tripping language.",
                "screenshot_url": "https://placeholder.com/screenshot1.png",
            },
            {
                "id": 2,
                "pattern": "Hidden costs",
                "severity": "medium",
                "description": "Extra fees are revealed only at checkout.",
                "screenshot_url": "https://placeholder.com/screenshot2.png",
            },
            {
                "id": 3,
                "pattern": "Trick questions",
                "severity": "low",
                "description": "Pre-ticked newsletter checkbox found on sign-up form.",
                "screenshot_url": "https://placeholder.com/screenshot3.png",
            },
        ],
        "score": 42,  # 0 = very dark, 100 = clean
    }


@app.post("/review")
async def review_audit(request: ReviewRequest):
    """
    Placeholder: Accepts an audit ID and optional human feedback,
    returns a fake AI-generated review summary.
    Real logic will pass findings + feedback back to Groq for re-analysis.
    """
    return {
        "audit_id": request.audit_id,
        "status": "reviewed",
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "summary": (
            "Based on the audit findings, this site employs several manipulative "
            "design patterns that negatively impact user autonomy. The most critical "
            "issue is confirm-shaming on the cookie consent banner."
        ),
        "recommendations": [
            "Replace guilt-tripping opt-out copy with neutral language.",
            "Surface all fees before the final checkout step.",
            "Uncheck the newsletter checkbox by default.",
        ],
        "feedback_received": request.feedback or "No feedback provided.",
    }


@app.get("/history")
async def get_history():
    """
    Placeholder: Returns a fake list of past audits.
    Real logic will query a database for persisted audit records.
    """
    return {
        "total": 3,
        "audits": [
            {
                "audit_id": "audit_11111",
                "url": "https://example-shop.com",
                "score": 35,
                "findings_count": 5,
                "timestamp": "2026-09-27T08:00:00",
            },
            {
                "audit_id": "audit_22222",
                "url": "https://another-site.com",
                "score": 68,
                "findings_count": 2,
                "timestamp": "2026-09-27T14:30:00",
            },
            {
                "audit_id": "audit_33333",
                "url": "https://dark-patterns-demo.com",
                "score": 12,
                "findings_count": 9,
                "timestamp": "2026-09-28T09:15:00",
            },
        ],
    }
