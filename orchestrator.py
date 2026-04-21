"""
AVA Orchestrator — multi-agent DeFi research with ERC-8004 identity + x402 payments.
China-marketable: supports Chinese language goals, focuses on global DeFi coordination.
"""
import asyncio, json, time, os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

import llm_client
from agent import SpecialistAgent, AgentEvent
from video_briefing import generate_briefing
from a2a_bus import BUS, A2AMessage
from tx_builder import extract_best_yield, build_defi_transaction

# Generic workflow task templates — used when LLM decomposition fails
FALLBACK_TASKS = [
    {"id": "t1", "type": "research",  "url": "https://www.google.com", "objective": "Research and gather information about the goal"},
    {"id": "t2", "type": "research",  "url": "https://www.google.com", "objective": "Find additional sources and verify findings"},
    {"id": "t3", "type": "verify",    "url": "https://www.google.com", "objective": "Cross-verify and synthesize all findings"},
]

# DeFi-specific tasks — used when goal mentions DeFi/yield/APY
DEFI_TASK_TEMPLATES = [
    {"id": "t1", "type": "research", "url": "https://app.aave.com",          "objective": "Find USDC and ETH supply APY rates on Aave V3"},
    {"id": "t2", "type": "research", "url": "https://app.morpho.org",         "objective": "Find best USDC yield opportunities on Morpho"},
    {"id": "t3", "type": "verify",   "url": "https://defillama.com/yields?token=USDC", "objective": "Verify and compare USDC APY across all protocols"},
]

DEFI_KEYWORDS = {"defi", "yield", "apy", "apr", "aave", "morpho", "compound", "usdc", "eth", "staking", "收益", "协议"}

# Sales prospect research tasks — used when goal mentions a person/company
SALES_TASK_TEMPLATES = [
    {"id": "t1", "type": "research", "url": "https://www.google.com", "objective": "Research the prospect's company: recent news, funding, product launches, and key initiatives"},
    {"id": "t2", "type": "research", "url": "https://www.google.com", "objective": "Research the prospect's role, background, and public professional activity"},
    {"id": "t3", "type": "verify",   "url": "https://www.google.com", "objective": "Find competitor context and industry trends relevant to this prospect's company"},
]
SALES_KEYWORDS = {"vp", "cto", "ceo", "cmo", "head of", "director", "founder", "manager", "sales", "growth", "engineer", "product", ".com", ".io", ".ai"}


class AVAOrchestrator:
    def __init__(self, headless: bool = True, on_update=None):
        self.headless = headless
        self.on_update = on_update or (lambda msg: print(f"[AVA] {msg}"))
        self.events: list[dict] = []
        self.all_screenshots: list[str] = []
        self.all_identities: list[dict] = []
        self.all_payments: list[dict] = []

    def _on_agent_event(self, event: AgentEvent):
        d = event.to_dict()
        self.events.append(d)
        if event.screenshot_b64:
            self.all_screenshots.append(event.screenshot_b64)
        self.on_update({
            "type": "agent_event",
            "agent_id": event.agent_id,
            "cycle": event.cycle,
            "url": event.url,
            "action": event.action,
            "vision": event.vision_check,
            "signature": event.signature,
            "payment": event.payment,
        })

    async def run(self, goal: str) -> dict:
        start = time.time()
        self.on_update({"type": "status", "msg": f"Goal: {goal}"})

        # Decompose goal — DeFi-aware
        self.on_update({"type": "status", "msg": "Orchestrator decomposing goal..."})
        try:
            plan = llm_client.orchestrate(goal)
            tasks = plan.get("tasks", [])[:3]
            # Use DeFi templates if goal is DeFi-related, else use LLM plan or fallback
            goal_lower = goal.lower()
            is_defi = any(kw in goal_lower for kw in DEFI_KEYWORDS)
            is_sales = any(kw in goal_lower for kw in SALES_KEYWORDS)
            if not tasks or all("google" in t.get("url","") for t in tasks):
                if is_defi:
                    tasks = DEFI_TASK_TEMPLATES
                elif is_sales:
                    tasks = SALES_TASK_TEMPLATES
                else:
                    tasks = FALLBACK_TASKS
                plan["summary"] = f"AVA workflow: {goal}"
        except Exception:
            is_defi = any(kw in goal.lower() for kw in DEFI_KEYWORDS)
            is_sales = any(kw in goal.lower() for kw in SALES_KEYWORDS)
            tasks = DEFI_TASK_TEMPLATES if is_defi else (SALES_TASK_TEMPLATES if is_sales else FALLBACK_TASKS)
            plan = {"tasks": tasks, "summary": goal}

        self.on_update({"type": "plan", "tasks": tasks, "summary": plan.get("summary", "")})

        # Launch agents in parallel
        self.on_update({"type": "status", "msg": f"Launching {len(tasks)} agents with ERC-8004 identities..."})

        # Register all agents on A2A bus
        for t in tasks:
            BUS.register(f"agent_{t['id']}")
        BUS.register("orchestrator")

        agents = [
            SpecialistAgent(f"agent_{t['id']}", t, self._on_agent_event, self.headless)
            for t in tasks
        ]
        results = await asyncio.gather(*[a.run() for a in agents], return_exceptions=True)

        agent_results = []
        for r in results:
            if isinstance(r, Exception):
                agent_results.append({"error": str(r)})
            else:
                agent_results.append(r)
                if "identity" in r:
                    self.all_identities.append(r["identity"])
                if "payments" in r:
                    self.all_payments.append(r["payments"])

        # Broadcast identity + payment summary
        self.on_update({"type": "identities", "identities": self.all_identities})
        self.on_update({"type": "payments", "payments": self.all_payments})

        # Broadcast A2A messages to dashboard
        self.on_update({"type": "a2a_messages", "messages": BUS.get_history()})

        # Extract best yield + build transaction preview
        self.on_update({"type": "status", "msg": "Building transaction preview..."})
        best_yield = await asyncio.to_thread(extract_best_yield, agent_results)
        tx = build_defi_transaction(
            protocol=best_yield.get("protocol", "Aave"),
            action="supply", asset="USDC", amount_usd=1.0,  # $1 demo amount
        )
        self.on_update({"type": "transaction", "best_yield": best_yield, "tx": tx})

        # Synthesize briefing
        self.on_update({"type": "status", "msg": "Synthesizing results..."})
        all_events = [e for r in agent_results if "events" in r for e in r["events"]]
        narration = llm_client.synthesize_briefing(all_events, goal)
        self.on_update({"type": "narration", "text": narration})

        # Generate visual briefing
        self.on_update({"type": "status", "msg": "Generating visual storyboard..."})
        briefing = generate_briefing(
            screenshots_b64=self.all_screenshots[:5],
            narration=narration,
            goal=goal,
            agent_events=all_events,
        )
        self.on_update({"type": "briefing", "briefing": {k: v for k, v in briefing.items() if k not in ("audio_b64",)}})

        elapsed = round(time.time() - start, 1)
        result = {
            "goal": goal,
            "plan": plan,
            "agent_results": agent_results,
            "identities": self.all_identities,
            "payments": self.all_payments,
            "narration": narration,
            "briefing": briefing,
            "total_events": len(self.events),
            "elapsed_sec": elapsed,
        }
        self.on_update({"type": "complete", "elapsed_sec": elapsed, "narration": narration})
        return result


async def run_cli(goal: str):
    def print_update(msg):
        if not isinstance(msg, dict):
            print(msg); return
        t = msg.get("type", "")
        if t == "status":       print(f"\n⚡ {msg['msg']}")
        elif t == "plan":
            print(f"\n📋 {msg.get('summary','')}")
            for task in msg.get("tasks", []):
                print(f"   [{task['type']}] {task['objective'][:60]}")
        elif t == "agent_event":
            sig = msg.get("signature", {})
            pay = msg.get("payment", {})
            print(f"   🤖 {msg['agent_id']} | {msg['action'][:50]}")
            if sig.get("signer"):
                print(f"      🔐 signed by {sig['signer'][:20]}...")
            if pay.get("nonce"):
                print(f"      💳 x402 payment: ${pay.get('amount_usdc',0):.6f} USDC")
        elif t == "identities":
            for ident in msg.get("identities", []):
                print(f"   🪪 ERC-8004 NFT #{ident.get('nft_id')} @ {ident.get('address','')[:20]}...")
        elif t == "narration":  print(f"\n📝 {msg['text']}")
        elif t == "complete":   print(f"\n✅ Done in {msg['elapsed_sec']}s")

    orch = AVAOrchestrator(headless=True, on_update=print_update)
    return await orch.run(goal)


if __name__ == "__main__":
    import sys
    goal = " ".join(sys.argv[1:]) or "Research top DeFi yield protocols and find best USDC APY"
    asyncio.run(run_cli(goal))
