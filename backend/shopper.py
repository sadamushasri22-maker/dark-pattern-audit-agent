import re
import logging
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

from static_server import ensure_static_server_running

logger = logging.getLogger(__name__)


def observe(url: str) -> List[Dict[str, Any]]:
    """
    Synchronous dynamic checker using Playwright (Python sync API, headless Chromium).
    Executed inside a dedicated worker thread via asyncio.to_thread(observe, url)
    to prevent Windows asyncio event loop collisions.

    1. Opens the URL twice in fresh page loads and reads any countdown element (id='timer' or 'Expires in MM:SS').
       If the starting value is the same both times or resets, returns:
       {type: "fake_urgency", evidence: "Timer showed MM:SS on load 1 and MM:SS on load 2"}
    2. Reads every price on the page (₹ amounts) and every checkbox with its checked state.
    Returns a list of observations with plain-English evidence strings.
    """
    # If URL targets local port 9000, ensure static server is active
    parsed = urlparse(url)
    if parsed.port == 9000 or "9000" in url:
        ensure_static_server_running(port=9000)

    observations: List[Dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            # ---------------------------------------------------------------
            # 1. Fresh Load 1: Read Timer, Checkboxes, Prices
            # ---------------------------------------------------------------
            context1 = browser.new_context()
            page1 = context1.new_page()
            page1.goto(url, wait_until="domcontentloaded", timeout=15000)
            page1.wait_for_timeout(350)

            timer_val_1: Optional[str] = None
            timer_el_1 = page1.query_selector("#timer, [id*='timer'], .timer, [class*='timer']")
            if timer_el_1:
                timer_val_1 = timer_el_1.inner_text().strip()
            else:
                body_text_1 = page1.inner_text("body")
                m1 = re.search(r"(?:Expires in|Flash Deal|reserved).*?(\d{1,2}:\d{2})", body_text_1, re.IGNORECASE)
                if m1:
                    timer_val_1 = m1.group(1).strip()

            # Read checkboxes
            checkboxes = page1.query_selector_all("input[type='checkbox']")
            for cb in checkboxes:
                cb_id = cb.get_attribute("id") or "unnamed_checkbox"
                is_checked = cb.is_checked()

                # Find descriptive label
                label_el = page1.query_selector(f"label[for='{cb_id}']")
                if label_el:
                    label_text = label_el.inner_text().strip().replace("\n", " ")
                else:
                    parent_handle = cb.evaluate_handle("el => el.closest('label') || el.parentElement")
                    parent_el = parent_handle.as_element()
                    if parent_el:
                        label_text = parent_el.inner_text().strip().replace("\n", " ")
                    else:
                        label_text = cb_id

                label_text = re.sub(r"\s+", " ", label_text).strip()
                if is_checked:
                    evidence_str = (
                        f"Checkbox '{cb_id}' ({label_text}) was pre-checked (checked=True) by default on initial page load."
                    )
                else:
                    evidence_str = (
                        f"Checkbox '{cb_id}' ({label_text}) was unchecked (checked=False) by default on initial page load."
                    )

                observations.append({
                    "type": "checkbox_state",
                    "evidence": evidence_str,
                    "checkbox_id": cb_id,
                    "checked": is_checked,
                    "label": label_text
                })

            # Read all ₹ amounts on page
            body_text = page1.inner_text("body")

            # Look specifically for order summary row prices
            summary_fees = page1.evaluate("""() => {
                const rows = [];
                const rowsEl = document.querySelectorAll('.summary-row, [class*="summary"], tr');
                for (const r of rowsEl) {
                    const text = r.innerText.trim().replace(/\\s+/g, ' ');
                    if (text.includes('₹') && text.length < 80) {
                        rows.push(text);
                    }
                }
                return rows;
            }""")

            all_detected_prices = re.findall(r"₹\s*[\d,]+(?:/[a-zA-Z]+)?", body_text)
            unique_prices = []
            for pr in all_detected_prices:
                cleaned_pr = re.sub(r"\s+", "", pr)
                if cleaned_pr not in unique_prices:
                    unique_prices.append(cleaned_pr)

            if unique_prices:
                prices_summary_str = f"Observed currency amounts on page: {', '.join(unique_prices)}."
                if summary_fees:
                    prices_summary_str += f" Line items in order summary: {'; '.join(summary_fees)}."

                observations.append({
                    "type": "price_observation",
                    "evidence": prices_summary_str,
                    "prices": unique_prices
                })

            # Detect any surprise fees in order summary
            for fee_item in summary_fees:
                fee_lower = fee_item.lower()
                if any(k in fee_lower for k in ["convenience", "platform", "booking", "handling", "processing"]):
                    observations.append({
                        "type": "hidden_fee",
                        "evidence": f"Order summary reveals extra charge: '{fee_item}' not disclosed in product display price."
                    })

            context1.close()

            # ---------------------------------------------------------------
            # 2. Fresh Load 2: Check Timer Reset / Persistence
            # ---------------------------------------------------------------
            context2 = browser.new_context()
            page2 = context2.new_page()
            page2.goto(url, wait_until="domcontentloaded", timeout=15000)
            page2.wait_for_timeout(350)

            timer_val_2: Optional[str] = None
            timer_el_2 = page2.query_selector("#timer, [id*='timer'], .timer, [class*='timer']")
            if timer_el_2:
                timer_val_2 = timer_el_2.inner_text().strip()
            else:
                body_text_2 = page2.inner_text("body")
                m2 = re.search(r"(?:Expires in|Flash Deal|reserved).*?(\d{1,2}:\d{2})", body_text_2, re.IGNORECASE)
                if m2:
                    timer_val_2 = m2.group(1).strip()

            context2.close()

            # Compare timers
            if timer_val_1 and timer_val_2:
                if timer_val_1 == timer_val_2:
                    observations.insert(0, {
                        "type": "fake_urgency",
                        "evidence": f"Timer showed {timer_val_1} on load 1 and {timer_val_2} on load 2"
                    })
                else:
                    observations.insert(0, {
                        "type": "timer_observation",
                        "evidence": f"Timer started at {timer_val_1} on load 1 and {timer_val_2} on load 2"
                    })

        finally:
            browser.close()

    return observations
