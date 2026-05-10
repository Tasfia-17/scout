"""
Filecoin Pin client — pins research reports to Filecoin via filecoin-pin CLI.
Each completed SCOUT run is stored with daily PDP cryptographic proofs.
"""
import json, os, subprocess, tempfile, re, hashlib

GATEWAY = "https://dweb.link/ipfs"


def pin_report(report: dict) -> dict:
    """
    Pin a research report JSON to Filecoin.
    Returns {"status": "pinned"|"simulated"|"error", "cid": "...", "gateway_url": "..."}
    """
    private_key = os.getenv("FILECOIN_PRIVATE_KEY", "")
    if not private_key:
        return _mock_pin(report)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, prefix="scout_report_") as f:
        json.dump(report, f, indent=2, default=str)
        tmp = f.name

    try:
        result = subprocess.run(
            ["filecoin-pin", "add", tmp],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "PRIVATE_KEY": private_key},
        )
        os.unlink(tmp)
        if result.returncode != 0:
            return {"status": "error", "error": result.stderr.strip()}
        cid = _parse_cid(result.stdout)
        if not cid:
            return {"status": "error", "error": "CID not found", "raw": result.stdout}
        return {"status": "pinned", "cid": cid, "gateway_url": f"{GATEWAY}/{cid}",
                "network": "filecoin-mainnet", "note": "Stored with daily PDP proofs"}
    except FileNotFoundError:
        os.unlink(tmp)
        return {"status": "error", "error": "filecoin-pin not installed. Run: npm install -g filecoin-pin"}
    except subprocess.TimeoutExpired:
        os.unlink(tmp)
        return {"status": "error", "error": "filecoin-pin timed out"}


def _parse_cid(output: str) -> str:
    m = re.search(r"Root CID:\s*(baf[a-z0-9]+)", output)
    return m.group(1) if m else ""


def _mock_pin(report: dict) -> dict:
    digest = hashlib.sha256(json.dumps(report, default=str).encode()).hexdigest()
    cid = f"bafybeif{digest[:52]}"
    return {"status": "simulated", "cid": cid, "gateway_url": f"{GATEWAY}/{cid}",
            "network": "filecoin-mainnet",
            "note": "Set FILECOIN_PRIVATE_KEY + install filecoin-pin CLI to pin for real"}
