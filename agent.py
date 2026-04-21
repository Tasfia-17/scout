"""
Specialist agent — browser task execution with ERC-8004 identity + x402 payments.
Every action is signed. Every API call has a payment receipt.
"""
import asyncio, time, json
from dataclasses import dataclass, field, asdict
from typing import Callable

import llm_client
from browser import BrowserController
from gap import generate_gap, compile_gap_to_js, GAPValidationError
from identity import AgentIdentity
from x402_client import X402Client
from a2a_bus import BUS, A2AMessage


@dataclass
class AgentEvent:
    agent_id: str
    cycle: int
    url: str
    action: str
    result: str
    screenshot_b64: str = ""
    vision_check: dict = field(default_factory=dict)
    signature: dict = field(default_factory=dict)   # ERC-8004 signed action
    payment: dict = field(default_factory=dict)     # x402 payment receipt
    elapsed_ms: int = 0
    ts: float = field(default_factory=time.time)

    def to_dict(self):
        d = asdict(self)
        d.pop("screenshot_b64")
        return d


class SpecialistAgent:
    def __init__(self, agent_id: str, task: dict, on_event: Callable, headless: bool = True):
        self.agent_id = agent_id
        self.task = task
        self.on_event = on_event
        self.headless = headless
        self.browser = BrowserController(headless=headless)
        self.identity = AgentIdentity(agent_id)
        self.x402 = X402Client()
        self.action_history: list[str] = []
        self.events: list[AgentEvent] = []
        self.extracted_data: dict = {}

    async def run(self, max_cycles: int = 5) -> dict:
        # ERC-8004 registration (simulated if no ETH on Taiko)
        identity_reg = await asyncio.to_thread(self.identity.register_on_chain)

        await self.browser.start()
        try:
            await self.browser.navigate(self.task["url"])

            for cycle in range(max_cycles):
                t0 = time.monotonic()
                ism = await self.browser.get_ism()
                screenshot_b64 = await self.browser.screenshot_b64()

                # Vision validation
                vision_check = {}
                if cycle > 0 and self.action_history:
                    vision_check = await asyncio.to_thread(
                        llm_client.validate_screenshot, screenshot_b64, self.action_history[-1]
                    )

                if self._goal_achieved(ism):
                    sig = self.identity.sign_action("goal_achieved", self.task["id"], cycle)
                    pay = self.x402.build_payment_payload(ism["url"])
                    self._emit(cycle, ism["url"], "goal_achieved", "Task complete",
                               screenshot_b64, vision_check, sig, pay["receipt"], t0)
                    break

                # Generate GAP
                try:
                    gap = await asyncio.to_thread(
                        generate_gap, self.task["objective"], ism,
                        "\n".join(self.action_history[-3:])
                    )
                except (GAPValidationError, Exception) as e:
                    self._emit(cycle, ism["url"], "gap_error", str(e),
                               screenshot_b64, {}, {}, {}, t0)
                    break

                actions = compile_gap_to_js(gap)
                action_desc = gap.get("summary", f"{len(actions)} actions")

                # Sign action with ERC-8004 identity
                sig = self.identity.sign_action(action_desc, self.task["id"], cycle)
                # x402 micropayment receipt
                pay = self.x402.build_payment_payload(ism["url"])

                for action in actions[:5]:
                    err = await self.browser.execute_action(action)
                    if err:
                        break

                await asyncio.sleep(0.5)
                self.action_history.append(action_desc)
                self.extracted_data[f"cycle_{cycle}"] = {
                    "url": ism["url"],
                    "title": ism["title"],
                    "body_snippet": ism.get("bodyText", "")[:500],
                }

                # Broadcast finding to other agents via A2A
                await BUS.send(A2AMessage(
                    sender=self.agent_id,
                    recipient="broadcast",
                    task_id=self.task["id"],
                    message_type="finding",
                    content={
                        "url": ism["url"],
                        "title": ism["title"],
                        "snippet": ism.get("bodyText", "")[:200],
                        "action": action_desc,
                        "signed_by": self.identity.address,
                    }
                ))

                self._emit(cycle, ism["url"], action_desc, gap.get("summary", ""),
                           screenshot_b64, vision_check, sig, pay["receipt"], t0)

        finally:
            await self.browser.stop()

        return {
            "agent_id": self.agent_id,
            "task": self.task,
            "identity": {
                "address": self.identity.address,
                "nft_id": self.identity.nft_id,
                "registration": identity_reg,
            },
            "payments": self.x402.get_payment_summary(),
            "events": [e.to_dict() for e in self.events],
            "extracted_data": self.extracted_data,
            "action_history": self.action_history,
        }

    def _goal_achieved(self, ism: dict) -> bool:
        """Stop when we have real data extracted, not just cycle count."""
        if len(self.action_history) < 2:
            return False
        # Check if we've extracted meaningful content (APY data, numbers, protocol names)
        all_text = " ".join(
            d.get("body_snippet", "") for d in self.extracted_data.values()
        ).lower()
        has_data = any(kw in all_text for kw in ["apy", "apr", "%", "supply", "borrow", "yield", "rate", "usdc"])
        return has_data or len(self.action_history) >= 4

    def _emit(self, cycle, url, action, result, screenshot_b64, vision_check, sig, payment, t0):
        event = AgentEvent(
            agent_id=self.agent_id, cycle=cycle, url=url,
            action=action, result=result, screenshot_b64=screenshot_b64,
            vision_check=vision_check, signature=sig, payment=payment,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )
        self.events.append(event)
        self.on_event(event)
