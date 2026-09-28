import os
import asyncio
from pathlib import Path

# Explicitly declare test mode and test bank ID
os.environ["TESTING"] = "1"
os.environ["HINDSIGHT_BANK_ID"] = "urbankart-test"

from httpx import AsyncClient, ASGITransport
from main import app

# Clear previous history for clean test
hist_file = Path("audit_history.json")
if hist_file.exists():
    hist_file.unlink()

async def main():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        print("=" * 60)
        print("1. RUNNING AUDIT ON store_v1 (Target bank: urbankart-test)")
        print("=" * 60)
        res_v1 = await ac.post("/audit", json={"site": "urbankart-test", "version": "store_v1"})
        data_v1 = res_v1.json()
        print("Bank used:", data_v1.get("site"))
        assert data_v1.get("site") == "urbankart-test", "Must use urbankart-test!"
        print("Findings count:", data_v1.get("findings_count"))
        print("Fixed issues:", data_v1.get("fixed_issues"))
        for f in data_v1.get("findings", []):
            print(f" - {f['type']} -> [{f.get('status')}]")

        print("\n" + "=" * 60)
        print("2. POSTING REVIEW: confirmed hidden fee (Safe test bank)")
        print("=" * 60)
        res_rev = await ac.post("/review", json={
            "site": "urbankart-test",
            "version": "store_v1",
            "finding_type": "hidden fee",
            "evidence": "Convenience fee 149",
            "decision": "confirmed",
            "note": "automated test confirmation"
        })
        rev_data = res_rev.json()
        print("Review response bank:", rev_data.get("site"))
        assert rev_data.get("site") == "urbankart-test", "Review must write to urbankart-test!"
        print("Sentence:", rev_data.get("retained_memory"))
        print("Saved to memory:", rev_data.get("saved_to_memory"))

        print("\n" + "=" * 60)
        print("3. RUNNING AUDIT ON store_v2 (expect STILL PRESENT & fixed issues)")
        print("=" * 60)
        res_v2 = await ac.post("/audit", json={"site": "urbankart-test", "version": "store_v2"})
        data_v2 = res_v2.json()
        print("Findings count:", data_v2.get("findings_count"))
        print("Fixed issues since", data_v2.get("prev_version"), ":", data_v2.get("fixed_issues"))
        for f in data_v2.get("findings", []):
            print(f" - {f['type']} -> [{f.get('status')}]")

        print("\n" + "=" * 60)
        print("4. RUNNING AUDIT ON store_v3 (expect hidden fee REGRESSION, others STILL PRESENT)")
        print("=" * 60)
        res_v3 = await ac.post("/audit", json={"site": "urbankart-test", "version": "store_v3"})
        data_v3 = res_v3.json()
        print("Findings count:", data_v3.get("findings_count"))
        print("Fixed issues since", data_v3.get("prev_version"), ":", data_v3.get("fixed_issues"))
        for f in data_v3.get("findings", []):
            print(f" - {f['type']} -> [{f.get('status')}]")

        print("\n" + "=" * 60)
        print("5. GET /history")
        print("=" * 60)
        res_hist = await ac.get("/history?site=urbankart-test")
        hist_data = res_hist.json()
        for ver, val in hist_data.get("by_version", {}).items():
            print(f"  Version: {ver} -> Counts: {val.get('counts')}, Total: {val.get('total')}")

if __name__ == "__main__":
    asyncio.run(main())
