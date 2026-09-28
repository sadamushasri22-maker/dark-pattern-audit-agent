import os
import sys
import logging
import asyncio
from typing import List, Dict, Any, Optional, Tuple, Set
from dotenv import load_dotenv
from hindsight_client import Hindsight

load_dotenv()

logger = logging.getLogger(__name__)

HINDSIGHT_BASE_URL = "https://api.hindsight.vectorize.io"
TEST_BANK_ID = "urbankart-test"

# In-memory mock storage when MOCK_HINDSIGHT=1
_mock_memory_banks: Dict[str, List[str]] = {}


def is_test_environment() -> bool:
    """Checks whether the current execution is running in an automated test or test mode."""
    return (
        os.getenv("TESTING", "").lower() in ["1", "true", "yes"]
        or "pytest" in sys.modules
        or os.getenv("PYTEST_CURRENT_TEST") is not None
    )


def is_sample_or_test_payload(note: Optional[str] = None, evidence: Optional[str] = None, site: Optional[str] = None) -> bool:
    """Detects whether a review call payload contains test or sample data."""
    if is_test_environment():
        return True
    if site and site.strip().lower() == TEST_BANK_ID:
        return True
    combined = f"{note or ''} {evidence or ''}".lower()
    test_keywords = ["unit test", "test note", "mock", "sample data", "test check", "test review"]
    return any(kw in combined for kw in test_keywords)


def get_default_bank_id() -> str:
    """
    Reads bank id from HINDSIGHT_BANK_ID in .env, defaulting to 'urbankart-demo'.
    If in test mode, safely returns 'urbankart-test'.
    """
    load_dotenv(override=True)
    if is_test_environment():
        return TEST_BANK_ID
    return os.getenv("HINDSIGHT_BANK_ID", "urbankart-demo").strip()


def resolve_safe_bank_id(bank_id: Optional[str], is_test_data: bool = False) -> str:
    """
    Resolves the target bank ID, strictly preventing automated tests or
    sample calls from writing to the real Hindsight bank.
    """
    default_real_bank = os.getenv("HINDSIGHT_BANK_ID", "urbankart-demo").strip()
    target_bank = (bank_id or "").strip()

    if not target_bank or target_bank == "urbankart":
        target_bank = default_real_bank

    if is_test_environment() or is_test_data or target_bank == TEST_BANK_ID:
        if target_bank == default_real_bank and default_real_bank != TEST_BANK_ID:
            logger.warning(
                f"Attempted test call against real bank '{default_real_bank}'. "
                f"Redirected to '{TEST_BANK_ID}' to protect the real Hindsight bank."
            )
        return TEST_BANK_ID

    return target_bank


_client: Optional[Hindsight] = None
_client_loop: Any = None


def get_hindsight_client() -> Optional[Hindsight]:
    """Returns Hindsight client bound to the current running event loop."""
    global _client, _client_loop
    api_key = os.getenv("HINDSIGHT_API_KEY")
    if not api_key:
        logger.warning("HINDSIGHT_API_KEY is not set.")
        return None

    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if _client is None or _client_loop != current_loop:
        _client = Hindsight(
            base_url=HINDSIGHT_BASE_URL,
            api_key=api_key,
            timeout=30.0
        )
        _client_loop = current_loop
    return _client


async def ensure_bank(client: Hindsight, bank_id: str) -> None:
    """Ensures that the memory bank exists."""
    if os.getenv("MOCK_HINDSIGHT", "").lower() in ["1", "true", "yes"]:
        if bank_id not in _mock_memory_banks:
            _mock_memory_banks[bank_id] = []
        return

    try:
        await client.acreate_bank(bank_id=bank_id, name=bank_id)
    except Exception:
        pass


async def recall_audit_memories(bank_id: Optional[str] = None) -> Tuple[List[str], Optional[str]]:
    """
    Recalls memories from the bank for reviewer decisions and fixed issues.
    Returns (list of memory strings, optional warning message if failed).
    """
    target_bank = resolve_safe_bank_id(bank_id)

    # Mock mode support
    if os.getenv("MOCK_HINDSIGHT", "").lower() in ["1", "true", "yes"]:
        return list(_mock_memory_banks.get(target_bank, [])), None

    client = get_hindsight_client()
    if not client:
        return [], "HINDSIGHT_API_KEY not configured. Memory recall skipped."

    recalled_texts: List[str] = []
    seen = set()

    queries = [
        "reviewer decisions and false alarms",
        "issues fixed in earlier audits"
    ]

    try:
        await ensure_bank(client, target_bank)

        for query in queries:
            try:
                resp = await client.arecall(bank_id=target_bank, query=query, max_tokens=2048)
                for item in getattr(resp, "results", []):
                    text = getattr(item, "text", "").strip()
                    if text and text not in seen:
                        seen.add(text)
                        recalled_texts.append(text)
            except Exception as q_err:
                logger.warning(f"Recall query '{query}' failed on bank '{target_bank}': {q_err}")

        return recalled_texts, None

    except Exception as e:
        warning_msg = f"Hindsight recall error: {str(e)}"
        logger.error(warning_msg)
        return [], warning_msg


async def retain_audit_summary(
    bank_id: Optional[str],
    version: str,
    current_findings: List[Dict[str, Any]],
    prev_version: Optional[str] = None,
    fixed_types: Optional[List[str]] = None,
    regression_types: Optional[Set[str]] = None
) -> Tuple[bool, str, Optional[str]]:
    """
    Retains an audit summary using version order and explicit 'earlier version' / 'later version' phrases.
    """
    target_bank = resolve_safe_bank_id(bank_id)

    current_types = sorted(list({f.get("type") for f in current_findings if f.get("type")}))
    current_str = ", ".join(current_types) if current_types else "none"

    if prev_version:
        fixed_str = ", ".join(fixed_types) if fixed_types else "none"
        summary = (
            f"Audit of {version} (later version than {prev_version}) for {target_bank}: "
            f"found issues: {current_str}. "
            f"Issues fixed compared to earlier version {prev_version}: {fixed_str}."
        )
    else:
        summary = (
            f"Audit of {version} (earliest version) for {target_bank}: "
            f"found issues: {current_str}. "
            f"Baseline earliest version with no earlier version to compare."
        )

    if regression_types:
        reg_str = ", ".join(sorted(list(regression_types)))
        summary += f" Regression alert: {reg_str} was fixed in an earlier version but reappeared in later version {version}."

    # Mock mode support
    if os.getenv("MOCK_HINDSIGHT", "").lower() in ["1", "true", "yes"]:
        if target_bank not in _mock_memory_banks:
            _mock_memory_banks[target_bank] = []
        _mock_memory_banks[target_bank].append(summary)
        return True, summary, None

    client = get_hindsight_client()
    if not client:
        return False, "", "HINDSIGHT_API_KEY not configured. Memory retain skipped."

    try:
        await ensure_bank(client, target_bank)
        await client.aretain(bank_id=target_bank, content=summary)
        return True, summary, None
    except Exception as e:
        warning_msg = f"Hindsight retain error: {str(e)}"
        logger.error(warning_msg)
        return False, summary, warning_msg


async def retain_review_decision(
    bank_id: Optional[str],
    version: str,
    finding_type: str,
    evidence: str,
    decision: str,
    note: Optional[str] = None
) -> Tuple[bool, str, Optional[str]]:
    """
    Retains a plain-English reviewer decision into Hindsight.
    Guarantees automated tests and sample calls write to 'urbankart-test' and never to the real bank.
    Includes evidence snippet for cross-version evidence matching.
    """
    is_test_data = is_sample_or_test_payload(note=note, evidence=evidence, site=bank_id)
    target_bank = resolve_safe_bank_id(bank_id, is_test_data=is_test_data)

    dec = decision.lower().strip()
    ev_clean = (evidence or "").strip().replace("\n", " ")
    ev_part = f" (evidence: '{ev_clean}')" if ev_clean else ""
    note_part = f" Note: {note.strip()}." if note and note.strip() else ""

    if dec == "confirmed":
        sentence = f"Reviewer confirmed {finding_type} in {version} as a real dark pattern{ev_part}.{note_part}"
    elif dec == "false_alarm":
        sentence = f"Reviewer marked {finding_type} in {version} as a false alarm{ev_part}.{note_part}"
    elif dec == "accepted":
        sentence = f"Reviewer accepted {finding_type} in {version} as a legitimate design pattern{ev_part}.{note_part}"
    else:
        sentence = f"Reviewer reviewed {finding_type} in {version} with decision '{decision}'{ev_part}.{note_part}"

    # Mock mode support
    if os.getenv("MOCK_HINDSIGHT", "").lower() in ["1", "true", "yes"]:
        if target_bank not in _mock_memory_banks:
            _mock_memory_banks[target_bank] = []
        _mock_memory_banks[target_bank].append(sentence)
        return True, sentence, None

    client = get_hindsight_client()
    if not client:
        return False, "", "HINDSIGHT_API_KEY not configured. Review retain skipped."

    try:
        await ensure_bank(client, target_bank)
        await client.aretain(
            bank_id=target_bank,
            content=sentence,
            metadata={
                "version": version,
                "finding_type": finding_type,
                "decision": dec
            }
        )
        return True, sentence, None
    except Exception as e:
        warning_msg = f"Hindsight retain review error: {str(e)}"
        logger.error(warning_msg)
        return False, sentence, warning_msg
