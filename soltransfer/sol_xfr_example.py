import time
import os
from dotenv import load_dotenv
from sol_xfr import send_sol, send_tkn

# Load environment variables
load_dotenv()

rpc_url='https://api.mainnet-beta.solana.com'

# show details controls how much print it writes to screen
# N just returns the txn_hash or FAIL
show_details_yn='Y'

# these set the priority fees for the transaction
# 4/8/2024 These are pretty high, a week ago, they could be set at 0 and go through
# priority fee tho is around $0.015 for total SOL fee
cu_prc   = 50000
cu_lmt   = 250000

# Get source wallet details from environment variables
src_addr = os.getenv('SOL_SRC_ADDR')
src_key = os.getenv('SOL_SRC_KEY')

# Validate environment variables
if not src_addr or not src_key:
    raise ValueError("Missing required environment variables: SOL_SRC_ADDR or SOL_SRC_KEY")

# Destination address (you can also move this to .env if you want)
dest_addr = 'v35gVwQn8gA9zNfBSMwA3UYjHuGAhw1hAWyc7eg99uH'

#
#  SEND SOL
#
# This example sends 0.1337 SOL from wallet_1 (src) to wallet_2 (dest)
sol_amt_2_xfr  = 0.01
txn_hash = send_sol(
	src_addr        = src_addr, 
	src_key         = src_key, 
	dest_addr       = dest_addr, 
	amt_sol         = sol_amt_2_xfr, 
	cu_prc          = cu_prc, 
	cu_lmt          = cu_lmt, 
	rpc_url         = rpc_url, 
	show_details_yn = show_details_yn
	)
print(txn_hash)


print('')
print('')
print('cant jam up your account, waiting 20 seconds between transactions')
time.sleep(20)


# Sending Some USDC to destination wallet
tkn_amt_2_xfr       = 0.123456
tkn_addr            = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v' # USDC
txn_hash = send_tkn(
	src_addr        = src_addr, 
	src_key         = src_key, 
	dest_addr       = dest_addr, 
	tkn_addr        = tkn_addr, 
	tkn_amt         = tkn_amt_2_xfr, 
	cu_prc          = cu_prc, 
	cu_lmt          = cu_lmt, 
	rpc_url         = rpc_url, 
	show_details_yn = show_details_yn
	)
print(txn_hash)


print('')
print('')
print('cant jam up your account, waiting 20 seconds between transactions')
time.sleep(20)


# Sending All USDC to destination wallet
tkn_addr            = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v' # USDC
send_max            = True
txn_hash = send_tkn(
	src_addr        = src_addr, 
	src_key         = src_key, 
	dest_addr       = dest_addr, 
	tkn_addr        = tkn_addr, 
	send_max        = send_max, 
	cu_prc          = cu_prc, 
	cu_lmt          = cu_lmt, 
	rpc_url         = rpc_url, 
	show_details_yn = show_details_yn
	)
print(txn_hash)
