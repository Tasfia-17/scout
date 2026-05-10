"""
Filecoin Pin client — pins research reports, audio briefings, and agent identities
to Filecoin mainnet via filecoin-pin CLI. Daily PDP cryptographic proofs.
"""
import json, os, subprocess, tempfile, re, hashlib

GATEWAY  = "https://dweb.link/ipfs"
PDP_SCAN = "https://pdp.vxb.ai"


def _run_pin(path: str) -> dict:
    """Run filecoin-pin add on a file path. Returns {cid, gateway_url} or {error}."""
    private_key = os.getenv("FILECOIN_PRIVATE_KEY", "")
    try:
        result = subprocess.run(
            ["filecoin-pin", "add", path],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "PRIVATE_KEY": private_key},
        )
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
        cid = _parse_cid(result.stdout)
        if not cid:
            return {"error": "CID not found"}
        return {"cid": cid, "gateway_url": f"{GATEWAY}/{cid}"}
    except FileNotFoundError:
        return {"error": "filecoin-pin not installed. Run: npm install -g filecoin-pin"}
    except subprocess.TimeoutExpired:
        return {"error": "filecoin-pin timed out"}


def pin_report(report: dict) -> dict:
    """
    Pin the full research report JSON + agent identities JSON to Filecoin.
    Returns the combined result with report_cid, identities_cid, pdp_scan_url.
    """
    private_key = os.getenv("FILECOIN_PRIVATE_KEY", "")
    if not private_key:
        return _mock_pin(report)

    results = {}

    # Pin main report
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, prefix="scout_report_") as f:
        json.dump(report, f, indent=2, default=str)
        tmp = f.name
    r = _run_pin(tmp)
    os.unlink(tmp)
    if "error" in r:
        return {"status": "error", **r}
    results["cid"] = r["cid"]
    results["gateway_url"] = r["gateway_url"]

    # Pin agent identities separately
    identities = report.get("identities", [])
    if identities:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, prefix="scout_identities_") as f:
            json.dump({"goal": report.get("goal"), "identities": identities}, f, indent=2, default=str)
            tmp2 = f.name
        r2 = _run_pin(tmp2)
        os.unlink(tmp2)
        if "cid" in r2:
            results["identities_cid"] = r2["cid"]
            results["identities_gateway_url"] = r2["gateway_url"]

    return {
        "status": "pinned",
        "network": "filecoin-mainnet",
        "pdp_scan_url": PDP_SCAN,
        "note": "Stored with daily PDP cryptographic proofs",
        **results,
    }


def pin_audio(audio_bytes: bytes, label: str = "briefing") -> dict:
    """Pin an MP3 audio file to Filecoin. Returns {cid, gateway_url} or {error}."""
    private_key = os.getenv("FILECOIN_PRIVATE_KEY", "")
    if not private_key:
        digest = hashlib.sha256(audio_bytes[:256]).hexdigest()
        cid = f"bafybeig{digest[:52]}"
        return {"status": "simulated", "cid": cid, "gateway_url": f"{GATEWAY}/{cid}",
                "label": label, "note": "Set FILECOIN_PRIVATE_KEY to pin for real"}

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, prefix=f"scout_{label}_") as f:
        f.write(audio_bytes)
        tmp = f.name
    r = _run_pin(tmp)
    os.unlink(tmp)
    if "error" in r:
        return {"status": "error", "label": label, **r}
    return {"status": "pinned", "label": label, "network": "filecoin-mainnet",
            "pdp_scan_url": PDP_SCAN, **r}


def _parse_cid(output: str) -> str:
    m = re.search(r"Root CID:\s*(baf[a-z0-9]+)", output)
    return m.group(1) if m else ""


def _mock_pin(report: dict) -> dict:
    digest = hashlib.sha256(json.dumps(report, default=str).encode()).hexdigest()
    cid = f"bafybeif{digest[:52]}"
    id_digest = hashlib.sha256((digest + "identities").encode()).hexdigest()
    id_cid = f"bafybeig{id_digest[:52]}"
    return {
        "status": "simulated",
        "cid": cid,
        "gateway_url": f"{GATEWAY}/{cid}",
        "identities_cid": id_cid,
        "identities_gateway_url": f"{GATEWAY}/{id_cid}",
        "network": "filecoin-mainnet",
        "pdp_scan_url": PDP_SCAN,
        "note": "Set FILECOIN_PRIVATE_KEY + install filecoin-pin CLI to pin for real",
    }
