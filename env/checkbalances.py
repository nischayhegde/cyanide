import json
import os
from solana.rpc.api import Client
from solders.pubkey import Pubkey

rpc_url = "http://new-york.rpc.pinnaclenode.com"
input_file = os.path.join(os.path.dirname(__file__), "generated_wallets.jsonl")
output_file = os.path.join(os.path.dirname(__file__), "active_wallets.jsonl")

client = Client(rpc_url)

MIN_SOL = 0.01
LAMPORTS_PER_SOL = 1_000_000_000

def has_token_accounts(pubkey: str) -> bool:
    try:
        owner = Pubkey.from_string(pubkey)
        resp = client.get_token_accounts_by_owner(owner, {})
        return bool(resp.value)
    except Exception:
        return False

def get_sol_balance(pubkey: str) -> float:
    try:
        owner = Pubkey.from_string(pubkey)
        resp = client.get_balance(owner)
        print(resp)
        return resp.value / LAMPORTS_PER_SOL
    except Exception:
        return 0.0

with open(input_file, "r") as infile, open(output_file, "w") as outfile:
    for line in infile:
        wallet = json.loads(line)
        pubkey = wallet["public_key"]
        priv_hex = wallet["private_key_hex"]
        sol_balance = get_sol_balance(pubkey)
        has_tokens = has_token_accounts(pubkey)
        if sol_balance > MIN_SOL or has_tokens:
            json.dump({"public_key": pubkey, "private_key_hex": priv_hex}, outfile)
            outfile.write("\n")