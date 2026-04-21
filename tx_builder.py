"""
Transaction builder — generates unsigned DeFi transaction previews.
Bridges research → on-chain execution (Challenge 01).
Uses web3.py to build real EIP-1559 transactions for Aave/Morpho supply.
No private key needed — user signs in their own wallet.
"""
import json
from web3 import Web3

# Base Sepolia testnet (free ETH from faucet)
BASE_RPC = "https://base-sepolia.g.alchemy.com/v2/demo"
BASE_CHAIN_ID = 84532

# Aave V3 on Base Sepolia
AAVE_POOL_BASE = "0x07eA79F68B2B3df564D0A34F8e19791a8a4c28A9"
# USDC on Base Sepolia
USDC_BASE = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"

# Aave Pool ABI — supply function only
AAVE_SUPPLY_ABI = [{
    "inputs": [
        {"name": "asset", "type": "address"},
        {"name": "amount", "type": "uint256"},
        {"name": "onBehalfOf", "type": "address"},
        {"name": "referralCode", "type": "uint16"}
    ],
    "name": "supply",
    "outputs": [],
    "stateMutability": "nonpayable",
    "type": "function"
}]

# ERC-20 approve ABI
APPROVE_ABI = [{
    "inputs": [
        {"name": "spender", "type": "address"},
        {"name": "amount", "type": "uint256"}
    ],
    "name": "approve",
    "outputs": [{"name": "", "type": "bool"}],
    "stateMutability": "nonpayable",
    "type": "function"
}]


def build_defi_transaction(
    protocol: str,
    action: str,
    asset: str,
    amount_usd: float,
    user_address: str = "0x0000000000000000000000000000000000000001"
) -> dict:
    """
    Build an unsigned DeFi transaction preview.
    Returns human-readable + raw transaction data.
    protocol: "aave" | "morpho"
    action: "supply" | "withdraw"
    asset: "USDC" | "ETH"
    amount_usd: dollar amount
    """
    amount_atomic = int(amount_usd * 1_000_000)  # USDC has 6 decimals

    try:
        w3 = Web3(Web3.HTTPProvider(BASE_RPC, request_kwargs={"timeout": 8}))

        if protocol.lower() == "aave" and action == "supply":
            # Step 1: Approve USDC spend
            usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC_BASE), abi=APPROVE_ABI)
            approve_tx = usdc.functions.approve(
                Web3.to_checksum_address(AAVE_POOL_BASE),
                amount_atomic
            ).build_transaction({
                "chainId": BASE_CHAIN_ID,
                "from": Web3.to_checksum_address(user_address),
                "gas": 60000,
                "maxFeePerGas": w3.eth.gas_price,
                "maxPriorityFeePerGas": Web3.to_wei(0.001, "gwei"),
                "nonce": 0,
            })

            # Step 2: Supply to Aave
            pool = w3.eth.contract(address=Web3.to_checksum_address(AAVE_POOL_BASE), abi=AAVE_SUPPLY_ABI)
            supply_tx = pool.functions.supply(
                Web3.to_checksum_address(USDC_BASE),
                amount_atomic,
                Web3.to_checksum_address(user_address),
                0
            ).build_transaction({
                "chainId": BASE_CHAIN_ID,
                "from": Web3.to_checksum_address(user_address),
                "gas": 250000,
                "maxFeePerGas": w3.eth.gas_price,
                "maxPriorityFeePerGas": Web3.to_wei(0.001, "gwei"),
                "nonce": 1,
            })

            return {
                "status": "ready",
                "protocol": "Aave V3",
                "action": f"Supply {amount_usd} USDC",
                "chain": "Base Mainnet",
                "chain_id": BASE_CHAIN_ID,
                "steps": [
                    {
                        "step": 1,
                        "description": f"Approve {amount_usd} USDC for Aave Pool",
                        "to": USDC_BASE,
                        "data": approve_tx["data"],
                        "gas": approve_tx["gas"],
                    },
                    {
                        "step": 2,
                        "description": f"Supply {amount_usd} USDC to Aave V3",
                        "to": AAVE_POOL_BASE,
                        "data": supply_tx["data"],
                        "gas": supply_tx["gas"],
                    }
                ],
                "note": "Unsigned — connect wallet to sign and broadcast",
            }

    except Exception as e:
        pass

    # Fallback: return transaction structure without RPC call
    return {
        "status": "preview",
        "protocol": protocol.title(),
        "action": f"Supply {amount_usd} USDC",
        "chain": "Base Mainnet",
        "chain_id": BASE_CHAIN_ID,
        "steps": [
            {
                "step": 1,
                "description": f"Approve {amount_usd} USDC",
                "to": USDC_BASE,
                "data": f"0x095ea7b3...{amount_atomic:064x}",
                "gas": 60000,
            },
            {
                "step": 2,
                "description": f"Supply {amount_usd} USDC to {protocol.title()}",
                "to": AAVE_POOL_BASE if protocol.lower() == "aave" else "0x...",
                "data": f"0x617ba037...{amount_atomic:064x}",
                "gas": 250000,
            }
        ],
        "note": "Unsigned transaction preview — connect wallet to execute",
    }


def extract_best_yield(agent_results: list[dict]) -> dict:
    """Parse agent execution data to find the best yield recommendation."""
    import llm_client, re

    # Collect all body text from agents
    all_text = ""
    for r in agent_results:
        for cycle_data in r.get("extracted_data", {}).values():
            all_text += cycle_data.get("body_snippet", "") + "\n"

    if not all_text.strip():
        return {"protocol": "Aave", "apy": "~4%", "asset": "USDC", "confidence": "low"}

    resp = llm_client.chat([{
        "role": "user",
        "content": (
            f"From this DeFi research data, extract the best USDC yield opportunity.\n"
            f"Data: {all_text[:1500]}\n"
            f"Reply ONLY with JSON: {{\"protocol\": \"name\", \"apy\": \"X.X%\", \"asset\": \"USDC\", \"confidence\": \"high/medium/low\"}}"
        )
    }], model="qwen3-8b", max_tokens=80)

    content = re.sub(r'<think>.*?</think>', '', resp.content or "", flags=re.DOTALL)
    match = re.search(r'\{.*\}', content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass
    return {"protocol": "Aave", "apy": "~4%", "asset": "USDC", "confidence": "low"}
