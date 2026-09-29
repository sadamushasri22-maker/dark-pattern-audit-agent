import os
import re
import json
import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set

HISTORY_FILE = Path(__file__).resolve().parent / "audit_history.json"

VERSION_ORDER = ["store_v1", "store_v2", "store_v3"]

def get_version_rank(version: str) -> int:
    """Returns the 0-based rank of a version based on store_v1 < store_v2 < store_v3."""
    v = version.lower().strip()
    if v in VERSION_ORDER:
        return VERSION_ORDER.index(v)
    m = re.search(r"v(\d+)", v)
    if m:
        return int(m.group(1)) - 1
    return 0

def get_immediately_previous_version(current_version: str) -> Optional[str]:
    """Returns the immediately preceding version according to version order."""
    rank = get_version_rank(current_version)
    if rank > 0 and (rank - 1) < len(VERSION_ORDER):
        return VERSION_ORDER[rank - 1]
    elif rank > 0:
        return f"store_v{rank}"
    return None

def get_active_bank_id() -> str:
    """Returns the current bank id from environment or .env without hardcoded fallback."""
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=True)
    else:
        load_dotenv(override=True)
    bank_id = os.getenv("HINDSIGHT_BANK_ID")
    if bank_id and bank_id.strip():
        return bank_id.strip()
    return "default"

def _load_history_dict() -> Dict[str, List[Dict[str, Any]]]:
    """Loads audit_history.json as a dictionary keyed by bank ID."""
    if not HISTORY_FILE.exists():
        return {}
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
        elif isinstance(data, list):
            # Backwards compatibility / migration: group existing list by site/bank
            migrated: Dict[str, List[Dict[str, Any]]] = {}
            for item in data:
                if isinstance(item, dict):
                    site_key = (item.get("site") or get_active_bank_id()).strip()
                    if site_key not in migrated:
                        migrated[site_key] = []
                    migrated[site_key].append(item)
            _save_history_dict(migrated)
            return migrated
        return {}
    except Exception:
        return {}

def _save_history_dict(data: Dict[str, List[Dict[str, Any]]]) -> None:
    """Saves the dictionary of history keyed by bank ID to audit_history.json."""
    try:
        HISTORY_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass

def _get_bank_history(bank_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns the audit history list strictly for the given bank ID."""
    target = (bank_id or get_active_bank_id()).strip()
    history_dict = _load_history_dict()
    return history_dict.get(target, [])

def get_latest_audit_for_version(site: str, version: str) -> Optional[Dict[str, Any]]:
    """Returns the latest audit record strictly for a specific version of a bank/site."""
    history = _get_bank_history(site)
    norm_ver = version.lower().strip()
    for rec in reversed(history):
        if rec.get("version", "").lower().strip() == norm_ver:
            return rec
    return None

def get_fixed_issues_compared_to_previous_version(
    site: str,
    current_version: str,
    current_findings: List[Dict[str, Any]]
) -> Tuple[Optional[str], List[str]]:
    """
    'fixed' = issue types present in the immediately previous VERSION's latest audit
    that are absent in this one.
    Never compares with itself or with later versions.
    """
    prev_version = get_immediately_previous_version(current_version)
    if not prev_version:
        return None, []

    prev_audit = get_latest_audit_for_version(site=site, version=prev_version)
    if not prev_audit:
        return prev_version, []

    prev_types = {f.get("type") for f in prev_audit.get("findings", []) if f.get("type")}
    current_types = {f.get("type") for f in current_findings if f.get("type")}

    fixed_types = sorted(list(prev_types - current_types))
    return prev_version, fixed_types

def get_earlier_versions_fixed_issues(
    site: str,
    current_version: str
) -> Set[str]:
    """
    Finds all issue types that were recorded as fixed in ANY earlier version's audit
    (i.e. where rank < current_version rank).
    Never compares with itself or with later versions.
    """
    current_rank = get_version_rank(current_version)
    earlier_fixed: Set[str] = set()

    for rank in range(1, current_rank):
        earlier_ver = VERSION_ORDER[rank] if rank < len(VERSION_ORDER) else f"store_v{rank+1}"
        prev_ver = VERSION_ORDER[rank - 1] if (rank - 1) < len(VERSION_ORDER) else f"store_v{rank}"

        earlier_audit = get_latest_audit_for_version(site=site, version=earlier_ver)
        prev_audit = get_latest_audit_for_version(site=site, version=prev_ver)

        if earlier_audit and prev_audit:
            prev_types = {f.get("type") for f in prev_audit.get("findings", []) if f.get("type")}
            earlier_types = {f.get("type") for f in earlier_audit.get("findings", []) if f.get("type")}
            earlier_fixed.update(prev_types - earlier_types)

    return earlier_fixed

def get_previous_version_types(site: str, current_version: str) -> Set[str]:
    """Returns finding types present in the immediately previous version's latest audit."""
    prev_ver = get_immediately_previous_version(current_version)
    if not prev_ver:
        return set()
    prev_audit = get_latest_audit_for_version(site=site, version=prev_ver)
    if not prev_audit:
        return set()
    return {f.get("type", "").lower().strip() for f in prev_audit.get("findings", []) if f.get("type")}

def record_audit(
    audit_id: str,
    site: str,
    version: str,
    findings: List[Dict[str, Any]],
    recalled_memories: List[str]
) -> Dict[str, Any]:
    """Records an audit run keyed by bank id in audit_history.json."""
    bank_key = (site or get_active_bank_id()).strip()
    status_counts = {"new": 0, "regression": 0, "still present": 0}
    for f in findings:
        st = f.get("status", "new").lower()
        status_counts[st] = status_counts.get(st, 0) + 1

    record = {
        "audit_id": audit_id,
        "site": bank_key,
        "version": version,
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "counts_by_status": status_counts,
        "total_findings": len(findings),
        "findings": findings,
        "recalled_memories_count": len(recalled_memories)
    }

    history_dict = _load_history_dict()
    if bank_key not in history_dict:
        history_dict[bank_key] = []
    history_dict[bank_key].append(record)
    _save_history_dict(history_dict)
    return record

def get_history_summary(site: Optional[str] = None) -> Dict[str, Any]:
    """
    Returns, per audit version, the count of findings by status for the bank id.
    Sorted by version order (store_v1 < store_v2 < store_v3).
    """
    bank_key = (site or get_active_bank_id()).strip()
    history = _get_bank_history(bank_key)

    by_version: Dict[str, Any] = {}
    history_list: List[Dict[str, Any]] = []

    for rec in history:
        ver = rec.get("version", "unknown")
        counts = rec.get("counts_by_status", {"new": 0, "regression": 0})
        total = rec.get("total_findings", 0)
        ts = rec.get("timestamp")

        by_version[ver] = {
            "counts": counts,
            "total": total,
            "last_audited": ts
        }

        history_list.append({
            "audit_id": rec.get("audit_id"),
            "site": rec.get("site"),
            "version": ver,
            "counts": counts,
            "total": total,
            "timestamp": ts
        })

    # Sort by_version according to VERSION_ORDER
    sorted_by_version = {}
    for ver in VERSION_ORDER:
        if ver in by_version:
            sorted_by_version[ver] = by_version[ver]
    for ver, val in by_version.items():
        if ver not in sorted_by_version:
            sorted_by_version[ver] = val

    return {
        "by_version": sorted_by_version,
        "audits": history_list
    }
