import os
import re
import json
import logging
from typing import List, Dict, Any, Optional, Tuple, Set
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert web usability and dark pattern auditor.
Your job is to analyze the provided HTML of a web page and identify any deceptive or manipulative design patterns (Dark Patterns).

Only detect patterns strictly belonging to these 5 categories:
1. fake urgency - countdown timers, artificial scarcity, or expiration claims that reset or are not tied to genuine inventory/events. Note: Genuine fixed-date sale banners (e.g., holiday or seasonal sales with a fixed calendar date like '25 Oct 2026') are legitimate and NOT fake urgency.
2. hidden fee - unexpected charges (convenience fee, platform fee, surprise checkout charges) not disclosed upfront in the primary pricing. If the checkout summary shows only the base price with no surprise extra fee, do NOT report a hidden fee. (Note: Recurring subscription memberships belong to category 5 'hard-to-cancel' and must NOT be classified as hidden fee).
3. pre-checked add-on - optional paid services, upgrades, insurance, or fast delivery checked by default without explicit user selection. If an add-on checkbox is unchecked by default, it is legitimate and NOT a pre-checked add-on.
4. confirm-shaming - opt-out language designed to guilt-trip, insult, or emotionally manipulate the user (e.g. "No, I don't want to save money").
5. hard-to-cancel - subscriptions or recurring memberships where cancellation terms or cancel links are intentionally buried, disguised in tiny/faint text, or obscured.

DYNAMIC PLAYWRIGHT CHECKER FACTS:
When dynamic browser runtime observations are provided (from Playwright headless Chromium tests), treat them as verified runtime facts:
- Reason over observed timer resets or identical countdown values across loads.
- Check actual checkbox default states (checked vs unchecked).
- Check actual currency amounts and order summary fee lines.
- Quote real observed evidence in your findings.

AUTHORITATIVE MEMORY & REVIEWER RULES:
You will be provided with recalled historical memories from previous audits and human reviewer decisions.
Follow these rules strictly:
(a) Audit strictly and ONLY what is currently present in the provided HTML and dynamic observations. Never report an issue that does not exist in the current page just because it was mentioned in past memories.
(b) CONFLICT RESOLUTION: When recalled memories conflict about the same issue, the MOST RECENT reviewer decision is the authoritative one.
(c) CROSS-VERSION EVIDENCE MATCHING: Never let a decision about one version's evidence suppress a finding in another version UNLESS the evidence text matches. If a reviewer marked an issue in an earlier version as false_alarm or accepted, only suppress a finding in the current version if the current element's evidence text matches that decision's evidence. If the current version has a distinct dark pattern element with different evidence, you MUST report it.
(d) If an element's pattern and evidence match an authoritative 'false_alarm' or 'accepted' decision, completely omit it.

You must respond ONLY with a JSON object in this exact schema:
{
  "findings": [
    {
      "type": "<one of: fake urgency, hidden fee, pre-checked add-on, confirm-shaming, hard-to-cancel>",
      "evidence": "<exact snippet of HTML code or observed runtime fact containing the pattern>",
      "explanation": "<short 1-2 sentence explanation of why this constitutes the dark pattern>",
      "status": "<new OR regression>"
    }
  ]
}

If no dark patterns from the list are found (or all potential findings are dismissed by authoritative reviewer decisions), return:
{
  "findings": []
}
"""


def parse_reviewer_decision(mem_text: str, order_idx: int) -> Optional[Dict[str, Any]]:
    """
    Parses a reviewer decision memory string into structured metadata.
    Handles sentences like:
      "Reviewer confirmed hidden fee in store_v1 as a real dark pattern (evidence: '...'). Note: ..."
      "Reviewer marked fake urgency in store_v1 as a false alarm."
      "Reviewer accepted confirm-shaming in store_v2 as a legitimate design pattern."
    """
    # Support correction sentences: "Reviewer changed decision on <type> in <version> from <prev> to <new>"
    change_pattern = re.compile(
        r"Reviewer\s+changed\s+decision\s+on\s+([a-zA-Z0-9_\-\s]+?)\s+in\s+([a-zA-Z0-9_\-]+)\s+from\s+([a-zA-Z0-9_\-\s]+?)\s+to\s+([a-zA-Z0-9_\-\s]+?)(?:\s*\((?:evidence|snippet):\s*['\"]?(.*?)['\"]?\))?(?:\.?\s*Note:\s*(.*?))?\.?$",
        re.IGNORECASE
    )
    m_change = change_pattern.search(mem_text.strip())
    if m_change:
        raw_type, version, from_dec, to_dec, evidence, note = m_change.groups()
        to_clean = to_dec.lower().strip()
        if "false_alarm" in to_clean or "false alarm" in to_clean:
            decision = "false_alarm"
        elif "accepted" in to_clean or "legitimate" in to_clean:
            decision = "accepted"
        elif "confirmed" in to_clean or "real dark pattern" in to_clean:
            decision = "confirmed"
        else:
            decision = to_clean
        return {
            "finding_type": raw_type.lower().strip(),
            "version": version.lower().strip(),
            "decision": decision,
            "evidence": evidence.strip() if evidence else None,
            "note": note.strip() if note else None,
            "raw_text": mem_text,
            "order_idx": order_idx
        }

    pattern = re.compile(
        r"Reviewer\s+(confirmed|marked|accepted|reviewed)\s+([a-zA-Z0-9_\-\s]+?)\s+in\s+([a-zA-Z0-9_\-]+)\s+as\s+([a-zA-Z0-9_\-\s]+?)(?:\s*\((?:evidence|snippet):\s*['\"]?(.*?)['\"]?\))?(?:\.?\s*Note:\s*(.*?))?\.?$",
        re.IGNORECASE
    )
    m = pattern.search(mem_text.strip())
    if not m:
        return None

    action, raw_type, version, raw_desc, evidence, note = m.groups()
    action = action.lower().strip()
    f_type = raw_type.lower().strip()
    version = version.lower().strip()
    desc = raw_desc.lower().strip()

    if "false alarm" in desc or action == "marked":
        decision = "false_alarm"
    elif "legitimate" in desc or "accepted" in desc or action == "accepted":
        decision = "accepted"
    elif "real dark pattern" in desc or "confirmed" in desc or action == "confirmed":
        decision = "confirmed"
    else:
        decision = action

    return {
        "finding_type": f_type,
        "version": version,
        "decision": decision,
        "evidence": evidence.strip() if evidence else None,
        "note": note.strip() if note else None,
        "raw_text": mem_text,
        "order_idx": order_idx
    }


def resolve_memory_conflicts(memories: List[str]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Parses memories and resolves conflicts so the most recent reviewer decision
    for the same issue is treated as authoritative.
    Returns (authoritative_decisions, general_audit_notes).
    """
    parsed_decisions: List[Dict[str, Any]] = []
    general_notes: List[str] = []

    for idx, mem in enumerate(memories):
        dec = parse_reviewer_decision(mem, order_idx=idx)
        if dec:
            parsed_decisions.append(dec)
        else:
            general_notes.append(mem)

    # Group decisions by (finding_type, version, evidence) and (finding_type, version)
    # Higher order_idx = more recent decision
    authoritative: Dict[str, Dict[str, Any]] = {}
    for d in parsed_decisions:
        ev_norm = (d["evidence"] or "").lower().strip()
        key = f"{d['finding_type']}::{d['version']}::{ev_norm}"
        authoritative[key] = d

    resolved = sorted(authoritative.values(), key=lambda x: x["order_idx"])
    return resolved, general_notes


def should_suppress_finding(
    finding_type: str,
    evidence: str,
    current_version: str,
    authoritative_decisions: List[Dict[str, Any]]
) -> bool:
    """
    Applies the rule:
    1. When recalled memories conflict about the same issue, treat the most recent
       reviewer decision as the authoritative one.
    2. Never let a decision about one version's evidence suppress a finding in another
       version unless the evidence text matches.
    """
    f_type = finding_type.lower().strip()
    ev_norm = evidence.lower().strip()
    cur_ver = current_version.lower().strip()

    # Search in reverse order (most recent decision first)
    for d in reversed(authoritative_decisions):
        if d["finding_type"] != f_type:
            continue

        dec_ver = d["version"].lower().strip()
        decision = d["decision"]
        dec_ev = (d["evidence"] or "").lower().strip()

        # If most recent authoritative decision is "confirmed", do NOT suppress!
        if decision == "confirmed":
            if dec_ver == cur_ver or (dec_ev and (dec_ev in ev_norm or ev_norm in dec_ev)):
                return False
            continue

        # If decision is "false_alarm" or "accepted":
        if dec_ver == cur_ver:
            # Same version: if specific evidence, check match; if general decision on this version, suppress
            if not dec_ev or (dec_ev in ev_norm or ev_norm in dec_ev):
                return True
        else:
            # Different version: NEVER suppress UNLESS evidence text matches!
            if dec_ev and (dec_ev in ev_norm or ev_norm in dec_ev):
                return True

    return False


def _extract_findings(content: str) -> List[Dict[str, str]]:
    """Parse JSON and normalize findings list with status field."""
    parsed = json.loads(content)
    if isinstance(parsed, dict):
        raw_list = parsed.get("findings", [])
    elif isinstance(parsed, list):
        raw_list = parsed
    else:
        raw_list = []

    clean_findings = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        p_type = item.get("type") or item.get("pattern") or "unknown"
        p_evidence = item.get("evidence") or item.get("snippet") or ""
        p_explanation = item.get("explanation") or item.get("description") or ""
        p_status = item.get("status", "new")
        if str(p_status).lower().strip() not in ["new", "regression"]:
            p_status = "new"
        clean_findings.append({
            "type": str(p_type).lower().strip(),
            "evidence": str(p_evidence).strip(),
            "explanation": str(p_explanation).strip(),
            "status": str(p_status).lower().strip()
        })
    return clean_findings


def audit_page(
    html: str,
    current_version: str = "store_v1",
    recalled_memories: Optional[List[str]] = None,
    observations: Optional[List[Dict[str, Any]]] = None
) -> List[Dict[str, str]]:
    """
    Audits page HTML for dark patterns using Groq (openai/gpt-oss-120b).
    Incorporates:
    1. Dynamic Playwright observations (real runtime facts).
    2. Authoritative recalled memories with conflict resolution and cross-version evidence matching.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        logger.error("GROQ_API_KEY not found in environment.")
        return []

    client = Groq(api_key=api_key)

    # 1. Resolve conflicts among recalled memories
    authoritative_decisions, general_notes = resolve_memory_conflicts(recalled_memories or [])

    memory_section = ""
    if recalled_memories:
        decisions_summary = []
        for d in authoritative_decisions:
            ev_str = f" [Evidence: '{d['evidence']}']" if d["evidence"] else ""
            decisions_summary.append(
                f"- [AUTHORITATIVE DECISION] {d['finding_type']} in {d['version']}: "
                f"ruling={d['decision'].upper()}{ev_str} (from: {d['raw_text']})"
            )

        general_summary = [f"- {m}" for m in general_notes if m]

        all_mem_bullets = "\n".join(decisions_summary + general_summary)
        memory_section = (
            f"RECALLED MEMORIES & AUTHORITATIVE REVIEWER DECISIONS FOR AUDITING {current_version}:\n"
            f"{all_mem_bullets}\n\n"
            f"IMPORTANT COMPLIANCE INSTRUCTIONS:\n"
            f"1. Most Recent Decision is Authoritative: When memories conflict about the same issue, follow the most recent decision above.\n"
            f"2. Cross-Version Evidence Rule: A decision about an earlier version's evidence (e.g. false_alarm on store_v1) "
            f"MUST NEVER suppress a finding in {current_version} unless the evidence text matches. "
            f"If {current_version} contains a dark pattern element whose evidence differs, you MUST report it.\n"
            f"3. Do NOT report anything in {current_version} that matches an authoritative false_alarm or accepted decision.\n\n"
        )

    # 2. Dynamic Playwright runtime observations section
    obs_section = ""
    if observations:
        obs_bullets = "\n".join(
            [f"- [{o.get('type')}]: {o.get('evidence')}" for o in observations if o.get("evidence")]
        )
        obs_section = (
            f"DYNAMIC RUNTIME BROWSER OBSERVATIONS (PLAYWRIGHT CHECKER FACTS):\n"
            f"Headless Chromium dynamically executed this page and observed the following real runtime facts:\n"
            f"{obs_bullets}\n\n"
            f"DYNAMIC REASONING RULES:\n"
            f"- Use these runtime browser observations as verified ground-truth facts.\n"
            f"- For 'fake urgency': cite the observed timer behavior (e.g., 'Timer showed 09:59 on load 1 and 09:59 on load 2').\n"
            f"- For 'pre-checked add-on': if a checkbox was observed pre-checked (checked=True) by default on initial page load for a paid service (e.g. priorityAddon), you MUST report it. If unchecked (checked=False), do NOT report it.\n"
            f"- For 'hidden fee': if an extra fee (such as 'Convenience Fee ₹149') was observed in the order summary that is not in the base product price, you MUST report it as a hidden fee. If no surprise fee is in the order summary, do NOT report a hidden fee.\n\n"
        )

    user_content = (
        f"{memory_section}"
        f"{obs_section}"
        f"Please audit this HTML for dark patterns in {current_version}:\n\n```html\n{html}\n```"
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content}
    ]

    models_to_try = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    raw_findings: List[Dict[str, str]] = []

    for model_name in models_to_try:
        max_attempts = 2
        success = False
        for attempt in range(1, max_attempts + 1):
            try:
                response = client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0.1,
                )
                raw_content = response.choices[0].message.content or "{}"
                raw_findings = _extract_findings(raw_content)
                if raw_findings:
                    success = True
                    break
                # If parsed findings were empty on first attempt, retry once
                success = True
                break

            except json.JSONDecodeError as jde:
                logger.warning(f"JSON decode failed on model {model_name} attempt {attempt}: {jde}")
                if attempt < max_attempts:
                    messages.append({
                        "role": "user",
                        "content": "Your previous response was not valid JSON. Please output only valid JSON matching the schema."
                    })
                else:
                    break
            except Exception as e:
                err_str = str(e).lower()
                logger.warning(f"Error calling {model_name} on attempt {attempt}: {e}")
                if "rate_limit" in err_str or "429" in err_str:
                    logger.info(f"Rate limit encountered for {model_name}. Switching to fallback model.")
                    break
                if attempt < max_attempts:
                    import time
                    time.sleep(2.0)
                    continue
                break

        if success and raw_findings:
            break

    # 3. Strict Python-level suppression verification
    filtered_findings: List[Dict[str, str]] = []
    for f in raw_findings:
        f_type = f.get("type", "")
        f_ev = f.get("evidence", "")

        if should_suppress_finding(
            finding_type=f_type,
            evidence=f_ev,
            current_version=current_version,
            authoritative_decisions=authoritative_decisions
        ):
            logger.info(f"Suppressing finding '{f_type}' in {current_version} per authoritative reviewer ruling.")
            continue

        filtered_findings.append(f)

    return filtered_findings
