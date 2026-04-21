"""
Real x402 micropayment client.
Uses EIP-3009 transferWithAuthorization — gasless for sender.
Wallet needs USDC on Base mainnet, no ETH required.
"""
import base64, json, os, secrets, time, requests
from eth_account import Account
from eth_account.messages import encode_typed_data
from web3 import Web3

WALLET_PK   = os.getenv("WALLET_PRIVATE_KEY", "")
# Base Sepolia testnet — free ETH from faucet.base.org or alchemy.com/faucets/base-sepolia
BASE_RPC    = "https://base-sepolia.g.alchemy.com/v2/demo"
CHAIN_ID    = 84532
USDC        = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"  # USDC on Base Sepolia
FACILITATOR = "https://x402.org/facilitator"
CHAIN_ID    = 84532
USDC        = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"  # USDC on Base Sepolia
FACILITATOR = "https://x402.org/facilitator"

# EIP-3009 domain for USDC on Base
USDC_DOMAIN = {"name": "USD Coin", "version": "2", "chainId": CHAIN_ID, "verifyingContract": USDC}
USDC_TYPES  = {"TransferWithAuthorization": [
    {"name": "from",        "type": "address"},
    {"name": "to",          "type": "address"},
    {"name": "value",       "type": "uint256"},
    {"name": "validAfter",  "type": "uint256"},
    {"name": "validBefore", "type": "uint256"},
    {"name": "nonce",       "type": "bytes32"},
]}


class X402Client:
    def __init__(self):
        pk = WALLET_PK or ("0x" + "1877ecbfdbe48f883179847a2f0ff9b889ea2d1f51885d05a689537439da6cc7")
        self.account = Account.from_key(pk)
        self.address = self.account.address
        self.payments: list[dict] = []
        self._w3 = Web3(Web3.HTTPProvider(BASE_RPC, request_kwargs={"timeout": 8}))

    def build_payment_payload(self, resource_url: str, amount_usdc_cents: int = 1) -> dict:
        """
        Build a real EIP-3009 USDC payment payload.
        amount_usdc_cents: atomic USDC units (1 = $0.000001)
        Gasless — facilitator pays gas.
        """
        now = int(time.time())
        nonce = "0x" + secrets.token_hex(32)
        # Pay to a demo recipient (in production: the API provider's address)
        pay_to = "0x0000000000000000000000000000000000000001"

        message = {
            "from": self.address, "to": pay_to,
            "value": amount_usdc_cents,
            "validAfter": now - 1, "validBefore": now + 300,
            "nonce": nonce,
        }
        structured = encode_typed_data(domain_data=USDC_DOMAIN, message_types=USDC_TYPES, message_data=message)
        signed = self.account.sign_message(structured)

        payload = {
            "x402Version": 2,
            "resource": {"url": resource_url, "description": "AVA agent action", "mimeType": "application/json"},
            "accepted": {
                "scheme": "exact",
                "network": f"eip155:{CHAIN_ID}",
                "amount": str(amount_usdc_cents),
                "asset": USDC,
                "payTo": pay_to,
                "maxTimeoutSeconds": 300,
                "extra": {"assetTransferMethod": "eip3009", "name": "USDC", "version": "2"},
            },
            "payload": {
                "signature": signed.signature.hex(),
                "authorization": {
                    "from": self.address, "to": pay_to,
                    "value": str(amount_usdc_cents),
                    "validAfter": str(now - 1), "validBefore": str(now + 300),
                    "nonce": nonce,
                },
            },
        }

        receipt = {
            "url": resource_url,
            "amount_usdc": amount_usdc_cents / 1_000_000,
            "from": self.address,
            "timestamp": now,
            "nonce": nonce[:10] + "...",
            "signature": signed.signature.hex()[:20] + "...",
            "network": f"Base Sepolia (eip155:{CHAIN_ID})",
            "status": "signed",
            "header": base64.b64encode(json.dumps(payload).encode()).decode()[:30] + "...",
        }
        self.payments.append(receipt)
        return {"header_value": base64.b64encode(json.dumps(payload).encode()).decode(), "receipt": receipt}

    def get_usdc_balance(self) -> float:
        """Check real USDC balance on Base mainnet."""
        try:
            abi = [{"inputs":[{"name":"account","type":"address"}],"name":"balanceOf",
                    "outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]
            contract = self._w3.eth.contract(address=Web3.to_checksum_address(USDC), abi=abi)
            bal = contract.functions.balanceOf(self.address).call()
            return bal / 1_000_000
        except Exception:
            return 0.0

    def get_payment_summary(self) -> dict:
        total = sum(p["amount_usdc"] for p in self.payments)
        return {
            "wallet": self.address,
            "usdc_balance": self.get_usdc_balance(),
            "total_payments": len(self.payments),
            "total_usdc": round(total, 6),
            "payments": self.payments,
            "network": f"Base Sepolia (eip155:{CHAIN_ID})",
        }
