"""
A2A (Agent-to-Agent) message bus — in-memory pub/sub for agent coordination.
Implements Google A2A protocol structure: Task → Artifact pattern.
"""
import asyncio, time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class A2AMessage:
    sender: str
    recipient: str       # agent_id or "broadcast"
    task_id: str
    message_type: str    # "finding" | "instruction" | "result" | "artifact"
    content: dict
    ts: float = field(default_factory=time.time)


class A2ABus:
    """Simple in-memory A2A message bus. All agents share one instance."""

    def __init__(self):
        self._queues: dict[str, asyncio.Queue] = {}
        self._history: list[A2AMessage] = []

    def register(self, agent_id: str):
        if agent_id not in self._queues:
            self._queues[agent_id] = asyncio.Queue()

    async def send(self, msg: A2AMessage):
        self._history.append(msg)
        if msg.recipient == "broadcast":
            for q in self._queues.values():
                await q.put(msg)
        elif msg.recipient in self._queues:
            await self._queues[msg.recipient].put(msg)

    async def receive(self, agent_id: str, timeout: float = 2.0) -> A2AMessage | None:
        if agent_id not in self._queues:
            return None
        try:
            return await asyncio.wait_for(self._queues[agent_id].get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def get_history(self) -> list[dict]:
        return [{"sender": m.sender, "recipient": m.recipient,
                 "type": m.message_type, "content": m.content, "ts": m.ts}
                for m in self._history]


# Global bus instance shared across all agents
BUS = A2ABus()
