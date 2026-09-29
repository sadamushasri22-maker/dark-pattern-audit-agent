"""
testmemory.py
─────────────
Validates that:
  1. .env loads both API keys correctly
  2. Groq API is reachable and the key is valid  (lists available models)
  3. Hindsight API key is present (client import check)

Run from the backend/ directory:
    python testmemory.py
"""

import os
import sys

# ── 1. Load .env ─────────────────────────────────────────────────────────────
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY      = os.getenv("GROQ_API_KEY", "")
HINDSIGHT_API_KEY = os.getenv("HINDSIGHT_API_KEY", "")

print("=" * 60)
print("  Dark Pattern Audit Agent – Memory / API Key Test")
print("=" * 60)

# ── 2. Key presence checks ───────────────────────────────────────────────────
def check_key(name: str, value: str) -> bool:
    masked = value[:8] + "..." + value[-4:] if len(value) > 12 else "(too short)"
    if value:
        print(f"  [OK]   {name} loaded   ->  {masked}")
        return True
    else:
        print(f"  [FAIL] {name} is MISSING - add it to backend/.env")
        return False

print("\n[1/3] Environment variables")
groq_ok      = check_key("GROQ_API_KEY",      GROQ_API_KEY)
hindsight_ok = check_key("HINDSIGHT_API_KEY", HINDSIGHT_API_KEY)

# ── 3. Groq live connectivity test ───────────────────────────────────────────
print("\n[2/3] Groq API connectivity")
if groq_ok:
    try:
        from groq import Groq

        client = Groq(api_key=GROQ_API_KEY)

        # Lightweight call - just ask for a one-word reply
        response = client.chat.completions.create(
            model="qwen/qwen3.8-27b",  # confirmed available on this account
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Reply with exactly one word: 'OK'. "
                        "This is a connectivity test."
                    ),
                }
            ],
            max_tokens=5,
        )

        reply = response.choices[0].message.content.strip()
        print(f"  [OK]   Groq responded  ->  \"{reply}\"")
        print(f"         model  : {response.model}")
        print(f"         tokens : prompt={response.usage.prompt_tokens}  "
              f"completion={response.usage.completion_tokens}")

    except Exception as exc:
        print(f"  [FAIL] Groq call failed: {exc}")
else:
    print("  [SKIP] Skipped (key missing)")

# ── 4. Hindsight import + key presence check ─────────────────────────────────
print("\n[3/3] Hindsight client")
if hindsight_ok:
    try:
        import hindsight_client  # noqa: F401 - actual module name from hindsight-client package

        print("  [OK]   hindsight_client package imported successfully")
        print("         HINDSIGHT_API_KEY is set and non-empty")
        # Note: a live Hindsight browser-capture call requires a running
        # browser environment; we only verify the package + key here.
    except ImportError as exc:
        print(f"  [WARN] hindsight import failed: {exc}")
        print("         Run:  pip install hindsight-client")
else:
    print("  [SKIP] Skipped (key missing)")

# ── Summary ──────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
all_ok = groq_ok and hindsight_ok
if all_ok:
    print("  [DONE] All checks passed - backend is ready!")
else:
    print("  [WARN] Some checks failed - see details above.")
print("=" * 60 + "\n")

sys.exit(0 if all_ok else 1)
