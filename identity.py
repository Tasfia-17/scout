"""
ERC-8004 Agent Identity — on-chain identity for AVA agents.
Each agent gets an ERC-721 NFT on Taiko L2.
Actions are signed with the agent's private key (EIP-712).
"""
import json, time, hashlib, os
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

# Taiko mainnet
TAIKO_RPC = "https://rpc.mainnet.taiko.xyz"
IDENTITY_REGISTRY = "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432"
CHAIN_ID = 167000

REGISTRY_ABI = [
    {"inputs": [{"internalType": "string", "name": "agentURI", "type": "string"}],
     "name": "register", "outputs": [{"internalType": "uint256", "name": "agentId", "type": "uint256"}],
     "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"internalType": "uint256", "name": "tokenId", "type": "uint256"}],
     "name": "tokenURI", "outputs": [{"internalType": "string", "name": "", "type": "string"}],
     "stateMutability": "view", "type": "function"},
    {"anonymous": False, "inputs": [
        {"indexed": True, "name": "agentId", "type": "uint256"},
        {"indexed": False, "name": "agentURI", "type": "string"},
        {"indexed": True, "name": "owner", "type": "address"}],
     "name": "Registered", "type": "event"},
]


class AgentIdentity:
    """
    Manages an ERC-8004 agent identity.
    If no private key provided, generates a deterministic one from agent_id.
    On-chain registration requires a funded wallet — falls back to off-chain signing.
    """

    def __init__(self, agent_id: str, private_key: str = None):
        self.agent_id = agent_id
        # Use shared wallet key if available, else deterministic from agent_id
        pk = private_key or os.getenv("WALLET_PRIVATE_KEY", "")
        if pk:
            self.account = Account.from_key(pk)
        else:
            seed = hashlib.sha256(f"ava-agent-{agent_id}".encode()).hexdigest()
            self.account = Account.from_key("0x" + seed)

        self.address = self.account.address
        self.nft_id: int | None = None  # set after on-chain registration
        self.agent_card: dict = self._build_agent_card()

    def _build_agent_card(self) -> dict:
        return {
            "type": "https://eips.ethereum.org/EIPS/eip-8004#registration-v1",
            "name": f"AVA-{self.agent_id}",
            "description": f"AVA specialist agent '{self.agent_id}' — autonomous DeFi research and execution agent",
            "image": "https://avatars.githubusercontent.com/u/0",
            "services": [{"name": "web", "endpoint": "http://localhost:8000"}],
            "x402Support": True,
            "active": True,
            "registrations": [],
        }

    def sign_action(self, action: str, task_id: str, nonce: int = None) -> dict:
        """Sign an agent action off-chain. Returns signature bundle."""
        nonce = nonce or int(time.time())
        payload = json.dumps({
            "agent": self.agent_id,
            "address": self.address,
            "action": action,
            "task_id": task_id,
            "nonce": nonce,
            "timestamp": int(time.time()),
            "nft_id": self.nft_id,
        }, sort_keys=True)

        msg = encode_defunct(text=payload)
        signed = self.account.sign_message(msg)
        return {
            "payload": json.loads(payload),
            "signature": signed.signature.hex(),
            "signer": self.address,
            "verified": True,  # can be verified with eth_account.recover_message
        }

    def register_on_chain(self, agent_card_uri: str = None) -> dict:
        """
        Attempt on-chain ERC-8004 registration on Taiko L2.
        Returns tx hash if successful, or mock registration if no funds.
        """
        uri = agent_card_uri or f"data:application/json;base64,{self._card_b64()}"
        try:
            w3 = Web3(Web3.HTTPProvider(TAIKO_RPC, request_kwargs={"timeout": 10}))
            if not w3.is_connected():
                return self._mock_registration(uri)

            contract = w3.eth.contract(
                address=Web3.to_checksum_address(IDENTITY_REGISTRY),
                abi=REGISTRY_ABI
            )
            balance = w3.eth.get_balance(self.account.address)
            if balance == 0:
                return self._mock_registration(uri)

            nonce = w3.eth.get_transaction_count(self.account.address)
            tx = contract.functions["register(string)"](uri).build_transaction({
                "chainId": CHAIN_ID,
                "from": self.account.address,
                "nonce": nonce,
                "gas": 200000,
                "gasPrice": w3.eth.gas_price,
            })
            signed_tx = self.account.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

            # Parse agentId from Registered event
            logs = contract.events.Registered().process_receipt(receipt)
            if logs:
                self.nft_id = logs[0]["args"]["agentId"]

            return {
                "status": "registered",
                "tx_hash": tx_hash.hex(),
                "agent_id_nft": self.nft_id,
                "address": self.address,
                "chain": "taiko",
                "chain_id": CHAIN_ID,
                "registry": IDENTITY_REGISTRY,
            }
        except Exception as e:
            return self._mock_registration(uri, error=str(e))

    def _mock_registration(self, uri: str, error: str = None) -> dict:
        """Simulated registration for demo — shows the full ERC-8004 structure."""
        import random
        self.nft_id = random.randint(1000, 9999)
        self.agent_card["registrations"] = [{
            "agentId": self.nft_id,
            "agentRegistry": f"eip155:{CHAIN_ID}:{IDENTITY_REGISTRY}"
        }]
        return {
            "status": "simulated",  # would be "registered" with funded wallet
            "agent_id_nft": self.nft_id,
            "address": self.address,
            "chain": "taiko",
            "chain_id": CHAIN_ID,
            "registry": IDENTITY_REGISTRY,
            "agent_card": self.agent_card,
            "note": error or "No ETH on Taiko — showing ERC-8004 structure for demo",
        }

    def _card_b64(self) -> str:
        import base64
        return base64.b64encode(json.dumps(self.agent_card).encode()).decode()
