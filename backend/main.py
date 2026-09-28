import os
import sys
import random
import logging
import datetime
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

# On Windows, set WindowsProactorEventLoopPolicy to prevent subprocess/Playwright issues
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from audit import audit_page
from shopper import observe
from static_server import start_static_server, stop_static_server
from hindsight_service import (
    recall_audit_memories,
    retain_audit_summary,
    retain_review_decision,
    get_hindsight_client,
    get_default_bank_id,
    resolve_safe_bank_id,
    is_sample_or_test_payload,
    TEST_BANK_ID
)
from history_store import (
    record_audit,
    get_history_summary,
    get_fixed_issues_compared_to_previous_version,
    get_earlier_versions_fixed_issues,
    get_previous_version_types
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure local static server for sample_sites/ (port 9000) starts on backend start
    start_static_server(port=9000)
    yield
    # Stop local static server on backend shutdown
    stop_static_server()
    client = get_hindsight_client()
    if client:
        try:
            await client.aclose()
        except Exception:
            pass


app = FastAPI(
    title="Dark Pattern Audit Agent API",
    version="0.4.1",
    lifespan=lifespan
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class AuditRequest(BaseModel):
    site: Optional[str] = None
    version: Optional[str] = "store_v1"
    site_name: Optional[str] = None
    url: Optional[str] = None
    options: Optional[dict] = {}


class ReviewRequest(BaseModel):
    site: Optional[str] = None
    version: Optional[str] = "store_v1"
    finding_type: str
    evidence: Optional[str] = ""
    decision: str  # confirmed, false_alarm, accepted
    note: Optional[str] = ""
    audit_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/audit")
async def run_audit(request: AuditRequest):
    """
    Runs dark pattern audit with Hindsight memory & Playwright dynamic checker.
    1. Uses safe bank resolution (real bank for production, 'urbankart-test' for tests).
    2. Recalls memories with conflict resolution (most recent decision authoritative).
    3. Runs synchronous Playwright observe(url) inside a dedicated thread with
       asyncio.to_thread to prevent Windows event loop conflicts.
    4. Audits page with Groq, reasoning over dynamic observations and quoting real evidence.
    5. Evaluates version order (store_v1 < store_v2 < store_v3) for status labels.
    6. Retains summary and persists history.
    """
    bank_id = resolve_safe_bank_id(request.site)

    # Resolve target version file
    raw_version = request.version or request.site_name or request.url
    if raw_version in [None, "", "urbankart", "urbankart-demo", "urbankart-test"]:
        raw_version = "store_v1"

    base_name = os.path.basename(str(raw_version).strip()).replace("/", "").replace("\\", "")
    if not base_name.endswith(".html"):
        base_name += ".html"

    version_label = base_name.replace(".html", "")

    sample_sites_dir = Path(__file__).resolve().parent.parent / "sample_sites"
    file_path = sample_sites_dir / base_name

    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Sample site file '{base_name}' not found in sample_sites/ directory."
        )

    try:
        html_content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read site HTML: {str(e)}")

    warnings: List[str] = []

    # 1. Recall past memories from Hindsight
    recalled_memories, recall_warning = await recall_audit_memories(bank_id=bank_id)
    if recall_warning:
        warnings.append(recall_warning)

    # 2. Dynamic Playwright runtime observation via asyncio.to_thread in a dedicated worker thread
    target_url = f"http://localhost:9000/{base_name}"
    observations: Optional[List[Dict[str, Any]]] = None

    try:
        observations = await asyncio.to_thread(observe, target_url)
    except Exception as e:
        err_type = type(e).__name__
        err_repr = repr(e)
        logger.warning(f"Playwright observe({target_url}) failed [{err_type}]: {err_repr}")
        warnings.append(
            f"Dynamic observation via Playwright failed ({err_type}: {err_repr}); fell back to HTML-only audit."
        )
        observations = None

    # 3. Run Groq audit with memory rules & dynamic runtime observations
    raw_findings = audit_page(
        html=html_content,
        current_version=version_label,
        recalled_memories=recalled_memories,
        observations=observations
    )

    # 4. Apply strict version order comparison:
    earlier_fixed_set = get_earlier_versions_fixed_issues(site=bank_id, current_version=version_label)
    prev_version_types = get_previous_version_types(site=bank_id, current_version=version_label)
    prev_version, fixed_types = get_fixed_issues_compared_to_previous_version(
        site=bank_id,
        current_version=version_label,
        current_findings=raw_findings
    )

    # Status classification:
    findings: List[Dict[str, Any]] = []
    for f in raw_findings:
        f_type = f.get("type", "").lower().strip()
        if f_type in earlier_fixed_set:
            status = "regression"
        elif f_type in prev_version_types:
            status = "still present"
        else:
            status = "new"

        findings.append({
            "type": f.get("type"),
            "evidence": f.get("evidence"),
            "explanation": f.get("explanation"),
            "status": status
        })

    regression_types = {f["type"] for f in findings if f["status"] == "regression"}

    fake_audit_id = f"audit_{random.randint(10000, 99999)}"

    # 5. Retain summary into Hindsight memory
    _, _, retain_warning = await retain_audit_summary(
        bank_id=bank_id,
        version=version_label,
        current_findings=findings,
        prev_version=prev_version,
        fixed_types=fixed_types,
        regression_types=regression_types
    )
    if retain_warning:
        warnings.append(retain_warning)

    # 6. Persist audit to history
    record_audit(
        audit_id=fake_audit_id,
        site=bank_id,
        version=version_label,
        findings=findings,
        recalled_memories=recalled_memories
    )

    response_payload = {
        "audit_id": fake_audit_id,
        "site": bank_id,
        "version": version_label,
        "status": "completed",
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "findings": findings,
        "findings_count": len(findings),
        "recalled_memories": recalled_memories,
        "observations": observations or [],
        "fixed_issues": fixed_types,
        "prev_version": prev_version,
    }
    if warnings:
        response_payload["warning"] = " | ".join(warnings)

    return response_payload


@app.post("/review")
async def review_audit(request: ReviewRequest):
    """
    Accepts reviewer decision (confirmed, false_alarm, or accepted) and
    retains a plain-English memory sentence in Hindsight.
    Guarantees automated tests and sample calls NEVER write to the real Hindsight bank.
    """
    is_test = is_sample_or_test_payload(note=request.note, evidence=request.evidence, site=request.site)
    bank_id = resolve_safe_bank_id(request.site, is_test_data=is_test)

    version = (request.version or "store_v1").strip()

    valid_decisions = ["confirmed", "false_alarm", "accepted"]
    decision = request.decision.strip().lower()
    if decision not in valid_decisions:
        decision = "confirmed"

    success, sentence, warning = await retain_review_decision(
        bank_id=bank_id,
        version=version,
        finding_type=request.finding_type,
        evidence=request.evidence or "",
        decision=decision,
        note=request.note
    )

    response_payload = {
        "status": "success" if success else "error",
        "saved_to_memory": success,
        "site": bank_id,
        "version": version,
        "decision": decision,
        "retained_memory": sentence,
    }
    if warning:
        response_payload["warning"] = warning

    return response_payload


@app.get("/history")
async def get_history(site: Optional[str] = None):
    """
    Returns, per audit version, the count of findings by status.
    """
    target_site = resolve_safe_bank_id(site)
    summary = get_history_summary(site=target_site)
    return {
        "by_version": summary["by_version"],
        "audits": summary["audits"],
        "total": len(summary["audits"])
    }
