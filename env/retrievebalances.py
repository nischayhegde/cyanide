import sys
import os
import json
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import base58

# Add the soltransfer module to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "soltransfer")))
from sol_xfr import send_sol

from solana.rpc.api import Client
from solders.pubkey import Pubkey

# Configuration
funderpubkey = "RAPEWkHm8YZJ6ECeaasbJdUp7E3XsxVYvLvHqCPSbT1"
rpc_url = "http://frankfurt.rpc.pinnaclenode.com"
input_file = os.path.join(os.path.dirname(__file__), "generated_wallets.jsonl")
min_gas = 0.000005000  # Minimum amount to keep for gas fees
cu_prc = 0
cu_lmt = 250000
MAX_WORKERS = 10  # Number of concurrent threads
LAMPORTS_PER_SOL = 1_000_000_000

client = Client(rpc_url)
write_lock = Lock()

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def safe_send_sol(*args, **kwargs):
    """Safe SOL transfer with retry logic"""
    max_retries = 3
    delay = 2
    for attempt in range(1, max_retries + 1):
        try:
            result = send_sol(*args, **kwargs)
            # Check if we got a valid result
            if result is not None:
                return result
            else:
                raise Exception("send_sol returned None")
        except Exception as e:
            error_msg = str(e)
            # Handle specific RPC error cases
            if "InternalErrorMessage" in error_msg or "has no attribute 'value'" in error_msg:
                logging.error(f"Attempt {attempt}: RPC error (likely network/node issue): {error_msg}")
            else:
                logging.error(f"Attempt {attempt}: Error sending SOL: {error_msg}")
            
            if attempt < max_retries:
                time.sleep(delay)
                delay *= 2
            else:
                logging.error(f"All {max_retries} attempts failed for send_sol")
                return None

def get_sol_balance(pubkey: str) -> float:
    """Get SOL balance for a given public key"""
    try:
        owner = Pubkey.from_string(pubkey)
        resp = client.get_balance(owner)
        
        # Check if response has value attribute (successful response)
        if hasattr(resp, 'value') and resp.value is not None:
            return resp.value / LAMPORTS_PER_SOL
        else:
            logging.warning(f"Invalid response for balance check {pubkey}: {resp}")
            return 0.0
            
    except Exception as e:
        logging.error(f"Error getting balance for {pubkey}: {e}")
        return 0.0

def retrieve_wallet_balance(wallet_data: dict) -> None:
    """Process a single wallet and send its balance back to funder"""
    pubkey = wallet_data["public_key"]
    private_key_array = wallet_data["private_key_array"]
    
    try:
        # Get current SOL balance
        sol_balance = get_sol_balance(pubkey)
        
        if sol_balance <= min_gas:
            print(f"- Skipping {pubkey}: Balance {sol_balance:.9f} SOL is too low (min gas: {min_gas})")
            return
        
        # Calculate amount to send (balance minus gas fee)
        amount_to_send = sol_balance - min_gas
        
        if amount_to_send <= 0:
            print(f"- Skipping {pubkey}: No balance to retrieve after gas fees")
            return
        
        # Convert private key to base58 format
        private_key_b58 = base58.b58encode(bytes(private_key_array)).decode()
        
        print(f"🔄 Retrieving {amount_to_send:.9f} SOL from {pubkey} (Balance: {sol_balance:.9f})")
        
        # Send SOL back to funder
        result = safe_send_sol(
            pubkey, 
            private_key_b58, 
            funderpubkey, 
            amount_to_send, 
            cu_prc, 
            cu_lmt, 
            rpc_url, 
            'Y'
        )
        
        if result:
            print(f"✅ Successfully retrieved {amount_to_send:.9f} SOL from {pubkey}")
            
            # Small delay to avoid overwhelming the RPC
            time.sleep(1)
            
            # Verify the transfer by checking new balance
            new_balance = get_sol_balance(pubkey)
            print(f"   New balance: {new_balance:.9f} SOL")
        else:
            print(f"❌ Failed to retrieve SOL from {pubkey}")
            
    except Exception as e:
        logging.error(f"Error processing wallet {pubkey}: {e}")

def main():
    """Main function to process all wallets"""
    # Check if input file exists
    if not os.path.exists(input_file):
        print(f"❌ Input file not found: {input_file}")
        return
    
    # Read all wallets
    wallets = []
    try:
        with open(input_file, "r") as infile:
            for line_num, line in enumerate(infile, 1):
                try:
                    wallet_data = json.loads(line.strip())
                    if "public_key" in wallet_data and "private_key_array" in wallet_data:
                        wallets.append(wallet_data)
                    else:
                        print(f"⚠️ Skipping invalid wallet data on line {line_num}")
                except json.JSONDecodeError as e:
                    print(f"⚠️ Error parsing JSON on line {line_num}: {e}")
    except Exception as e:
        print(f"❌ Error reading input file: {e}")
        return
    
    if not wallets:
        print("❌ No valid wallets found in the input file")
        return
    
    print(f"🚀 Starting balance retrieval for {len(wallets)} wallets...")
    print(f"📍 Funder wallet: {funderpubkey}")
    print(f"⛽ Minimum gas reserve: {min_gas} SOL")
    print(f"🔧 Using {MAX_WORKERS} concurrent threads")
    print("-" * 60)
    
    total_retrieved = 0.0
    successful_retrievals = 0
    
    # Process wallets with thread pool
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all tasks
        futures = [executor.submit(retrieve_wallet_balance, wallet) for wallet in wallets]
        
        # Process completed tasks
        completed = 0
        for future in as_completed(futures):
            completed += 1
            if completed % 50 == 0:
                print(f"📊 Processed {completed}/{len(wallets)} wallets...")
            
            try:
                future.result()  # This will raise any exceptions that occurred
                successful_retrievals += 1
            except Exception as e:
                logging.error(f"Task failed: {e}")
    
    # Final summary
    print("-" * 60)
    print(f"✅ Completed processing {len(wallets)} wallets")
    print(f"📈 Successful retrievals: {successful_retrievals}")
    print(f"💰 All retrieved SOL sent to: {funderpubkey}")
    
    # Check final funder balance
    final_funder_balance = get_sol_balance(funderpubkey)
    print(f"🏦 Final funder balance: {final_funder_balance:.9f} SOL")

if __name__ == "__main__":
    main()
