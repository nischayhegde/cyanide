import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from solana.rpc.api import Client
from solana.rpc.types import TokenAccountOpts
from solders.pubkey import Pubkey

rpc_url = "http://frankfurt.rpc.pinnaclenode.com"
input_file = os.path.join(os.path.dirname(__file__), "generated_wallets.jsonl")
output_file = os.path.join(os.path.dirname(__file__), "active_wallets.jsonl")

client = Client(rpc_url)

MIN_SOL = 0.01
LAMPORTS_PER_SOL = 1_000_000_000
MAX_WORKERS = 20  # Number of concurrent threads

# Lock for thread-safe file writing
write_lock = Lock()

def has_token_accounts(pubkey: str) -> bool:
    owner = Pubkey.from_string(pubkey)
    SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
    resp = client.get_token_accounts_by_owner(
        owner,
        TokenAccountOpts(program_id=Pubkey.from_string(SPL_TOKEN_PROGRAM_ID))
    )
    return bool(resp.value)

def get_sol_balance(pubkey: str) -> float:
    try:
        owner = Pubkey.from_string(pubkey)
        resp = client.get_balance(owner)
        return resp.value / LAMPORTS_PER_SOL
    except Exception:
        return 0.0

def process_wallet(wallet_data: dict, outfile) -> None:
    """Process a single wallet and write to file if it meets criteria"""
    pubkey = wallet_data["public_key"]
    priv_hex = wallet_data["private_key_hex"]
    
    try:
        sol_balance = get_sol_balance(pubkey)
        has_tokens = has_token_accounts(pubkey)
        
        if sol_balance > MIN_SOL or has_tokens:
            # Thread-safe file writing
            with write_lock:
                json.dump({"public_key": pubkey, "private_key_hex": priv_hex}, outfile)
                outfile.write("\n")
                outfile.flush()  # Ensure data is written immediately
            
            print(f"✓ Active wallet found: {pubkey} (SOL: {sol_balance:.6f}, Tokens: {has_tokens})")
        else:
            print(f"- Empty wallet: {pubkey} (SOL: {sol_balance:.6f})")
            
    except Exception as e:
        print(f"✗ Error processing {pubkey}: {e}")

def main():
    # Read all wallets first
    wallets = []
    with open(input_file, "r") as infile:
        for line in infile:
            wallets.append(json.loads(line))
    
    print(f"Processing {len(wallets)} wallets with {MAX_WORKERS} threads...")
    
    with open(output_file, "w") as outfile:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            # Submit all tasks
            futures = [executor.submit(process_wallet, wallet, outfile) for wallet in wallets]
            
            # Process completed tasks
            completed = 0
            for future in as_completed(futures):
                completed += 1
                if completed % 100 == 0:
                    print(f"Processed {completed}/{len(wallets)} wallets...")
                
                try:
                    future.result()  # This will raise any exceptions that occurred
                except Exception as e:
                    print(f"Task failed: {e}")
    
    print(f"✅ Completed processing {len(wallets)} wallets. Results saved to {output_file}")

if __name__ == "__main__":
    main()