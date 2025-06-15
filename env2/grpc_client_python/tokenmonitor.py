import os
import sys
import time
import grpc
import base58
import threading
import queue
import logging
import json
import signal
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock, Event
from typing import Dict, List, Set, Optional, Callable
import httpx

import generated.geyser_pb2 as pb_pb2
import generated.geyser_pb2_grpc as pb_pb2_grpc

# Configure logging
logging.basicConfig(level=logging.INFO, format='[%(levelname)s %(asctime)s] %(message)s')
logger = logging.getLogger(__name__)

node = {
    "url": "http://frankfurt.grpc.pinnaclenode.com",
    "grpcToken": ""
}

TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"

# Tokens to monitor for simple transfers
MONITORED_TOKENS = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": {"name": "USDC", "min_balance": 250, "min_transfer": 20},  # $50+ transfers
    "So11111111111111111111111111111111111111112": {"name": "WSOL", "min_balance": 2, "min_transfer": 0.2},  # 0.05+ SOL transfers  
    "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN": {"name": "JUP", "min_balance": 100, "min_transfer": 50},  # 50+ JUP transfers
    "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh": {"name": "WBTC", "min_balance": 0.003, "min_transfer": 0.0005},  # 0.0005+ WBTC transfers
    "27G8MtK7VtTcCHkpASjSDdkWWYfoqT6ggEuKidVJidD4": {"name": "JLP", "min_balance": 100, "min_transfer": 5},  # 5+ JLP transfers
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": {"name": "USDT", "min_balance": 20, "min_transfer": 200},  # $50+ transfers
}

# Threading configuration
MAX_WORKER_THREADS = 15  # Maximum concurrent transaction processors
QUEUE_MAX_SIZE = 2000    # Maximum queue size to prevent memory issues (increased)
processing_queue = queue.Queue(maxsize=QUEUE_MAX_SIZE)

# Account key activity tracking - using bytes for performance
account_key_activity: Dict[bytes, List[float]] = {}  # accountKey bytes -> array of timestamps
blacklisted_account_keys: Set[bytes] = set()
BLACKLIST_FILE = os.path.join(os.path.dirname(__file__), 'blacklisted_account_keys.json')

MAX_TRANSACTIONS_PER_PERIOD = 50
TIME_WINDOW = 3600000  # 1 hour in milliseconds
startup_time = time.time() * 1000  # Convert to milliseconds

# Locks for thread safety
activity_lock = Lock()
blacklist_lock = Lock()

# Shutdown event for graceful termination
shutdown_event = Event()

# HTTP client for poison endpoint (reuse connections)
poison_client = httpx.Client(
    timeout=0.1,  # 100ms timeout
    limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
    http2=False  # Disable HTTP/2 for simplicity
)

# Excluded account keys (system programs) - stored as bytes for fast comparison
EXCLUDED_ACCOUNT_KEYS_BYTES = {
    base58.b58decode('11111111111111111111111111111111'),
    base58.b58decode('ComputeBudget111111111111111111111111111111'),
    base58.b58decode('SysvarRent111111111111111111111111111111111'),
    base58.b58decode('ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL'),
    base58.b58decode('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'),
    base58.b58decode('EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'),
    base58.b58decode('SysvarRecentB1ockHashes11111111111111111111'),
    base58.b58decode('So11111111111111111111111111111111111111112'),
    base58.b58decode('Sysvar1nstructions1111111111111111111111111'),
    base58.b58decode('SysvarC1ock11111111111111111111111111111111')
}

# Permanently blacklisted account keys - these can never be unblacklisted
PERMANENTLY_BLACKLISTED_KEYS_BYTES = {
        base58.b58decode('9obNtb5GyUegcs3a1CbBkLuc5hEWynWfJC6gjz5uWQkE'),
    base58.b58decode('AobVSwdW9BbpMdJvTqeCN4hPAmh4rHm7vwLnQ5ATSyrS'),
    base58.b58decode('A77HErqtfN1hLLpvZ9pCtu66FEtM8BveoaKbbMoZ4RiR'),
    base58.b58decode('ASTyfSima4LLAdDgoFGkgqoKowG1LZFDr9fAQrg7iaJZ'),
    base58.b58decode('43DbAvKxhXh1oSxkJSqGosNw3HpBnmsWiak6tB5wpecN'),
    base58.b58decode('2AQdpHJ2JpcEgPiATUXjQxA8QmafFegfQwSLWSprPicm'),
    base58.b58decode('is6MTRHEgyFLNTfYcuV4QBWLjrZBfmhVNYR6ccgr8KV'),
    base58.b58decode('D89hHJT5Aqyx1trP6EnGY9jJUB3whgnq3aUvvCqedvzf'),
    base58.b58decode('RBHdGVfDfMjfU6iUfCb1LczMJcQLx7hGnxbzRsoDNvx'),
    base58.b58decode('FWznbcNXWQuHTawe9RxvQ2LdCENssh12dsznf4RiouN5'),
    base58.b58decode('Fe7SEekiKygziaEGKxsDsgLVzrCfNvVBvAYsaJBwFA8s'),
    base58.b58decode('57vSaRTqN9iXaemgh4AoDsZ63mcaoshfMK8NP3Z5QNbs'),
    base58.b58decode('FpwQQhQQoEaVu3WU2qZMfF1hx48YyfwsLoRgXG83E99Q'),
    base58.b58decode('FxteHmLwG9nk1eL4pjNve3Eub2goGkkz6g6TbvdmW46a'),
    base58.b58decode('BmFdpraQhkiDQE6SnfG5omcA1VwzqfXrwtNYBwWTymy6'),
    base58.b58decode('G9X7F4JzLzbSGMCndiBdWNi5YzZZakmtkdwq7xS3Q3FE'),
    base58.b58decode('H8sMJSCQxfKiFTCfDR3DUMLPwcRbM61LGFJ8N4dK3WjS'),
    base58.b58decode('9un5wqE3q4oCjyrDkwsdD48KteCJitQX5978Vh7KKxHo'),
    base58.b58decode('u6PJ8DtQuPFnfmwHbGFULQ4u4EgjDiyYKjVEsynXq2w'),
    base58.b58decode('5VCwKtCXgCJ6kit5FybXjvriW3xELsFDhYrPSqtJNmcD'),
    base58.b58decode('97UQvPXbadGSsVaGuJCBLRm3Mkm7A5DVJ2HktRzrnDTB'),
    base58.b58decode('DPqsobysNf5iA9w7zrQM8HLzCKZEDMkZsWbiidsAt1xo'),
    base58.b58decode('GJRs4FwHtemZ5ZE9x3FNvJ8TMwitKTh21yxdRPqn7npE'),
    base58.b58decode('AC5RDfQFmDS1deWZos921JfqscXdByf8BKHs5ACWjtW2'),
    base58.b58decode('2ojv9BAiHUrvsm9gxDe7fJSzbNZSJcxZvf8dqmWGHG8S'),
    base58.b58decode('5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9'),
    base58.b58decode('6FEVkH17P9y8Q9aCkDdPcMDjvj7SVxrTETaYEm8f51Jy'),
    base58.b58decode('HBxZShcE86UMmF93KUM8eWJKqeEXi5cqWCLYLMMhqMYm'),
    base58.b58decode('5PAhQiYdLBd6SVdjzBQDxUAEFyDdF5ExNPQfcscnPRj5'),
    base58.b58decode('59L2oxymiQQ9Hvhh92nt8Y7nDYjsauFkdb3SybdnsG6h'),
    base58.b58decode('53unSgGWqEWANcPYRF35B2Bgf8BkszUtcccKiXwGGLyr'),
    base58.b58decode('8s9j5qUtuE9PGA5s7QeAXEh5oc2UGr71pmJXgyiZMHkt'),
    base58.b58decode('BA7UdvSVywRisn8YLMpg6emrNNk3N3TFqSrKJXmTBKdt'),
    base58.b58decode('22Wnk8PwyWZV7BfkZGJEKT9jGGdtvu7xY6EXeRh7zkBa'),
    base58.b58decode('2E1UKoiiZPwsp4vn6tUh5k61kG2UqYpT7oBrFaJUJXXd'),
    base58.b58decode('3vxheE5C46XzK4XftziRhwAf8QAfipD7HXXWj25mgkom'),
    base58.b58decode('EqfdXQTL9r8yzjgeTx3nceJBxH3gAMBjiQrUzsf6oRhx'),
    base58.b58decode('4GC3a1RkRXx5shwGP8pTY6cxXgSWkbfc66vM53a6qSKj'),
    base58.b58decode('7mhcgF1DVsj5iv4CxZDgp51H6MBBwqamsH1KnqXhSRc5'),
    base58.b58decode('2kmT6TAgwy2aPt4wtiSmmosyTZ8kVRSXwXxtbgJ8QfLM'),
    base58.b58decode('8Mm46CsqxiyAputDUp2cXHg41HE3BfynTeMBDwzrMZQH'),
    base58.b58decode('2nE99H3e9gfbxKaGodnTwixMgZwgTtKg45aoCFwdEfJS'),
    base58.b58decode('8jjpnSUhm5UYghznhcdkwwEUFyke6z5TchHEtUUgW8hX'),
    base58.b58decode('3jn81xbBK95zf5A1K4jRMzTicWxKM6X8BzYWzhPtFjuF'),
    base58.b58decode('HVh6wHNBAsG3pq1Bj5oCzRjoWKVogEDHwUHkRz3ekFgt'),
    base58.b58decode('WR87TKyUfMDzGojFvRxq2f1xf7Jcgkvoc7Z2tDVLHdY'),
    base58.b58decode('6mearRPb9Bma9Ad9wCKnGtVbTeqDyZQ6PPxDRpBUNdJU'),
    base58.b58decode('2YERiDP8JqbmKDDUhPQtEfWozafQm1cdwi6KrmYo2app'),
    base58.b58decode('6VGNcrNuhwCwWZDQoA9QoyJxKtb4FEGLnieScUnLbeKJ'),
    base58.b58decode('A5QtrjyeJLZ62HqSZAmiqAboiBJZX3eQbCe4QSLBGXXN'),
    base58.b58decode('836euAuAeEWdjHFZ87vKhR6n4Vu1V22yMvj1MyzCdVU3'),
    base58.b58decode('Ahgd7ZczsP6XcWuhsF1Hn7i9W31uHMMPkmffrALL7ers'),
    base58.b58decode('H13inzihSqSgfhHrGXNcrhMPzZmp73Mjs1tu8PrnFN7K'),
    base58.b58decode('AgsYPSd9jQZEpbTMsvBWKdiAux3eyghdSY355QVHH9Hs'),
    base58.b58decode('9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM'),
    base58.b58decode('faczL4zr9Ss5U3sN829LgykeUZQ8BiNqkXPub6nUSHe'),
    base58.b58decode('D5LmzoS7PXmT8oMVpSY1iSk1bZD2XLsc9nE5rSmwvyuQ'),
    base58.b58decode('3yHvm5kFrEqYURBekXAXEpEWggpb8q51VRWDZtjZRQpT'),
    base58.b58decode('5SDrsMNTYdhmApjfqYHDvjoW92f2S42vcc7zNDVcQ9Ej'),
    base58.b58decode('3gd3dqgtJ4jWfBfLYTX67DALFetjc5iS72sCgRhCkW2u'),
    base58.b58decode('BbHG9GvPActFGogv3iNrpDAj4qpXr8t3jF16uGxXcKci'),
    base58.b58decode('6QJzieMYfp7yr3EdrePaQoG3Ghxs2wM98xSLRu8Xh56U'),
    base58.b58decode('G7vNg68KfbjVLCTc8Uw9JVmaC4ZajpX97ApkToBqvviy'),
    base58.b58decode('3yFwqXBfZY4jBVUafQ1YEXw189y2dN3V5KQq9uzBDy1E'),
    base58.b58decode('i57ExrKB2i4mSgjSuq2xz617mQXmu33WG2WEYypmdvX')
    # Add wallet addresses here that should always remain blacklisted
    # Example: base58.b58decode('YourWalletAddressHere123456789012345678901'),
}

# List of wallet addresses to be permanently blacklisted (easier to manage as strings)
PERMANENT_BLACKLIST_ADDRESSES = [
    # Add wallet addresses here as base58 strings
    # "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",  # Example Bitcoin address format
    # "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",  # Example Solana address
]

def initialize_permanent_blacklist():
    """Initialize the permanent blacklist from the string list"""
    added_count = 0
    for address in PERMANENT_BLACKLIST_ADDRESSES:
        try:
            address_bytes = base58.b58decode(address)
            PERMANENTLY_BLACKLISTED_KEYS_BYTES.add(address_bytes)
            # Also add to regular blacklist
            with blacklist_lock:
                blacklisted_account_keys.add(address_bytes)
            added_count += 1
        except Exception as e:
            logger.error(f"Failed to decode permanent blacklist address {address}: {e}")
    
    if added_count > 0:
        logger.info(f"Added {added_count} addresses to permanent blacklist")
        # Save once after adding all permanent addresses
        save_blacklist()

def load_blacklist():
    """Load blacklist from file"""
    try:
        if os.path.exists(BLACKLIST_FILE):
            with open(BLACKLIST_FILE, 'r') as f:
                blacklist_data = json.load(f)
                with blacklist_lock:
                    # Convert base58 strings back to bytes for internal storage
                    for b58_key in blacklist_data:
                        try:
                            blacklisted_account_keys.add(base58.b58decode(b58_key))
                        except Exception as e:
                            logger.warning(f"Failed to decode blacklisted key {b58_key}: {e}")
                logger.info(f"Loaded {len(blacklisted_account_keys)} blacklisted account keys")
    except Exception as e:
        logger.error(f"Error loading blacklist: {e}")

def save_blacklist():
    """Save blacklist to file"""
    try:
        with blacklist_lock:
            # Convert bytes to base58 strings only for file storage
            blacklist_array = [base58.b58encode(key).decode() for key in blacklisted_account_keys]
        with open(BLACKLIST_FILE, 'w') as f:
            json.dump(blacklist_array, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving blacklist: {e}")

def sweep_unblacklist():
    """Periodic sweep to unblacklist eligible account keys"""
    now = time.time() * 1000  # Convert to milliseconds
    to_unblacklist = []
    
    with blacklist_lock:
        blacklisted_keys = blacklisted_account_keys.copy()
    
    for account_key_bytes in blacklisted_keys:
        # Skip permanently blacklisted keys
        if is_permanently_blacklisted(account_key_bytes):
            continue
            
        with activity_lock:
            timestamps = account_key_activity.get(account_key_bytes, [])
            recent_timestamps = [ts for ts in timestamps if now - ts < TIME_WINDOW]
            
            # If activity is below threshold and time window has elapsed since startup, unblacklist
            if len(recent_timestamps) <= MAX_TRANSACTIONS_PER_PERIOD and (now - startup_time) >= TIME_WINDOW:
                to_unblacklist.append(account_key_bytes)
            
            # Update the activity record in case timestamps were trimmed
            account_key_activity[account_key_bytes] = recent_timestamps
    
    if to_unblacklist:
        with blacklist_lock:
            for key in to_unblacklist:
                blacklisted_account_keys.discard(key)
        save_blacklist()

def check_and_update_account_key_activity(account_key_bytes: bytes) -> bool:
    """Check if account key should be blacklisted or unblacklisted - using bytes for performance"""
    # Skip excluded system programs - fast bytes comparison
    if account_key_bytes in EXCLUDED_ACCOUNT_KEYS_BYTES:
        return False
    
    # Always return True for permanently blacklisted keys
    if is_permanently_blacklisted(account_key_bytes):
        # Ensure it's in the regular blacklist too (but don't save immediately)
        with blacklist_lock:
            if account_key_bytes not in blacklisted_account_keys:
                blacklisted_account_keys.add(account_key_bytes)
        return True
    
    now = time.time() * 1000  # Convert to milliseconds
    
    with activity_lock:
        # Get or create activity array for this account key
        if account_key_bytes not in account_key_activity:
            account_key_activity[account_key_bytes] = []
        
        timestamps = account_key_activity[account_key_bytes]
        
        # Remove timestamps older than the time window
        recent_timestamps = [ts for ts in timestamps if now - ts < TIME_WINDOW]
        
        # Add current timestamp
        recent_timestamps.append(now)
        
        # Update the activity record
        account_key_activity[account_key_bytes] = recent_timestamps
    
    with blacklist_lock:
        is_currently_blacklisted = account_key_bytes in blacklisted_account_keys
    
    # Check if account key should be blacklisted
    if len(recent_timestamps) > MAX_TRANSACTIONS_PER_PERIOD and not is_currently_blacklisted:
        with blacklist_lock:
            blacklisted_account_keys.add(account_key_bytes)
        save_blacklist()
        # Convert to base58 only for logging
        account_key_str = base58.b58encode(account_key_bytes).decode()
        return True
    
    return is_currently_blacklisted

def start_periodic_sweep():
    """Start periodic sweep for unblacklisting"""
    def sweep_worker():
        while not shutdown_event.is_set():
            # Sleep in smaller chunks to be responsive to shutdown
            for _ in range(300):  # 5 minutes = 300 seconds
                if shutdown_event.is_set():
                    break
                time.sleep(1)
            
            if shutdown_event.is_set():
                break
                
            try:
                sweep_unblacklist()
                # Also save blacklist periodically to catch any permanent keys added
                save_blacklist()
                
                # Log queue status for monitoring
                queue_size = processing_queue.qsize()
                with blacklist_lock:
                    blacklist_count = len(blacklisted_account_keys)
                permanent_count = len(PERMANENTLY_BLACKLISTED_KEYS_BYTES)
                
                # Include gRPC connection status
                grpc_status = "Connected" if stream_manager and stream_manager.is_connected else "Disconnected"
                reconnect_attempts = stream_manager.reconnect_attempts if stream_manager else 0
                
                logger.info(f"Status - Queue: {queue_size}/{QUEUE_MAX_SIZE}, Blacklisted: {blacklist_count}, Permanent: {permanent_count}, gRPC: {grpc_status} (attempts: {reconnect_attempts})")
                
            except Exception as e:
                logger.error(f"Error in periodic sweep: {e}")
        
        logger.info("Periodic sweep worker shutting down")
    
    sweep_thread = threading.Thread(target=sweep_worker, daemon=True, name="SweepWorker")
    sweep_thread.start()
    logger.info("Started periodic sweep thread")
    return sweep_thread

class GrpcStreamManager:
    """Manages gRPC stream connection with automatic reconnection and error handling"""
    
    def __init__(self, endpoint: str, auth_token: str, data_handler: Callable):
        self.endpoint = endpoint
        self.auth_token = auth_token
        self.data_handler = data_handler
        self.client = None
        self.stream = None
        self.is_connected = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 50
        self.base_reconnect_interval = 5.0  # seconds
        self.reconnect_timer = None
        self.ping_timer = None
        self.is_reconnecting = False
        self.connection_lock = Lock()
        
    def create_client(self):
        """Create a new gRPC client"""
        try:
            if self.endpoint.startswith("https://"):
                host = self.endpoint[len("https://"):]
                creds = grpc.ssl_channel_credentials()
                channel = grpc.secure_channel(host, creds)
            else:
                host = self.endpoint[len("http://"):]
                channel = grpc.insecure_channel(host)
            
            self.client = pb_pb2_grpc.GeyserStub(channel)
            self.channel = channel
            logger.info(f"Created gRPC client for {self.endpoint}")
            return True
        except Exception as e:
            logger.error(f"Failed to create gRPC client: {e}")
            return False
    
    def connect(self, subscription_request):
        """Establish gRPC connection and start streaming"""
        with self.connection_lock:
            try:
                # Clear any existing timers
                self.clear_timers()
                
                # Create client if needed
                if not self.client and not self.create_client():
                    raise Exception("Failed to create gRPC client")
                
                # Create subscription iterator
                if self.auth_token:
                    metadata = [("x-token", self.auth_token)]
                    self.stream = self.client.Subscribe(iter([subscription_request]), metadata=metadata)
                else:
                    self.stream = self.client.Subscribe(iter([subscription_request]))
                
                self.is_connected = True
                self.reconnect_attempts = 0
                self.is_reconnecting = False
                
                logger.info(f"gRPC connection established successfully to {self.endpoint}")
                
                # Start ping mechanism
                self.start_ping()
                
                return True
                
            except Exception as e:
                logger.error(f"Connection error: {e}")
                self.is_connected = False
                return False
    
    def start_streaming(self, subscription_request):
        """Start the streaming loop"""
        try:
            for msg in self.stream:
                if shutdown_event.is_set():
                    logger.info("Shutdown event detected, breaking from stream")
                    break
                    
                # Process the message
                try:
                    self.data_handler(msg)
                except Exception as e:
                    logger.error(f"Error in data handler: {e}")
                    
        except grpc.RpcError as e:
            if not shutdown_event.is_set():
                logger.error(f"gRPC RPC error: {e}")
                self.handle_disconnect(subscription_request)
        except Exception as e:
            if not shutdown_event.is_set():
                logger.error(f"gRPC stream error: {e}")
                self.handle_disconnect(subscription_request)
        finally:
            self.cleanup_connection()
    
    def handle_disconnect(self, subscription_request):
        """Handle stream disconnection and schedule reconnection"""
        if self.is_connected:
            logger.info("gRPC stream disconnected")
            self.is_connected = False
        
        self.cleanup_connection()
        
        if not self.is_reconnecting and not shutdown_event.is_set():
            self.schedule_reconnect(subscription_request)
    
    def schedule_reconnect(self, subscription_request):
        """Schedule reconnection with exponential backoff"""
        if shutdown_event.is_set():
            return
            
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error(f"Max reconnection attempts ({self.max_reconnect_attempts}) reached. Waiting 5 minutes before resetting...")
            self.reconnect_timer = threading.Timer(300.0, self.reset_reconnect_attempts)  # 5 minutes
            self.reconnect_timer.start()
            return
        
        self.is_reconnecting = True
        self.reconnect_attempts += 1
        
        # Exponential backoff with jitter
        backoff_seconds = min(
            self.base_reconnect_interval * (2 ** (self.reconnect_attempts - 1)),
            60.0  # Max 1 minute
        )
        jitter_seconds = backoff_seconds * 0.1 * (0.5 + 0.5 * time.time() % 1)  # Add jitter
        delay_seconds = backoff_seconds + jitter_seconds
        
        logger.info(f"Reconnecting... Attempt {self.reconnect_attempts}/{self.max_reconnect_attempts} (delay: {delay_seconds:.1f}s)")
        
        self.reconnect_timer = threading.Timer(delay_seconds, self.attempt_reconnect, args=[subscription_request])
        self.reconnect_timer.start()
    
    def attempt_reconnect(self, subscription_request):
        """Attempt to reconnect to the gRPC stream"""
        if shutdown_event.is_set():
            return
            
        try:
            # Recreate client every 5 attempts
            if self.reconnect_attempts % 5 == 0:
                logger.info("Recreating gRPC client...")
                self.cleanup_connection()
                if not self.create_client():
                    raise Exception("Failed to recreate gRPC client")
            
            if self.connect(subscription_request):
                logger.info("Reconnection successful")
                # Start streaming in a separate thread
                stream_thread = threading.Thread(
                    target=self.start_streaming, 
                    args=[subscription_request],
                    daemon=True,
                    name="GrpcStreamThread"
                )
                stream_thread.start()
            else:
                raise Exception("Connection failed")
                
        except Exception as e:
            logger.error(f"Reconnection failed: {e}")
            self.is_reconnecting = False
            if not shutdown_event.is_set():
                self.schedule_reconnect(subscription_request)
    
    def reset_reconnect_attempts(self):
        """Reset reconnection attempts after cooling off period"""
        logger.info("Resetting reconnection attempts after cooling off period")
        self.reconnect_attempts = 0
        # Could trigger a reconnection attempt here if needed
    
    def start_ping(self):
        """Start periodic ping to keep connection alive"""
        def ping_worker():
            ping_counter = 0
            while self.is_connected and not shutdown_event.is_set():
                try:
                    # Sleep in smaller intervals to be responsive to shutdown
                    for _ in range(30):  # 30 seconds total
                        if not self.is_connected or shutdown_event.is_set():
                            break
                        time.sleep(1)
                    
                    if self.is_connected and self.stream and not shutdown_event.is_set():
                        ping_counter += 1
                        # Simple heartbeat - just log that we're alive
                        logger.debug(f"gRPC connection heartbeat #{ping_counter}")
                        
                except Exception as e:
                    logger.debug(f"Ping worker error: {e}")
                    break
            
            logger.debug("Ping worker stopped")
        
        self.ping_timer = threading.Thread(target=ping_worker, daemon=True, name="PingWorker")
        self.ping_timer.start()
    
    def clear_timers(self):
        """Clear all timers"""
        if self.reconnect_timer:
            self.reconnect_timer.cancel()
            self.reconnect_timer = None
    
    def cleanup_connection(self):
        """Clean up connection resources"""
        self.is_connected = False
        
        if hasattr(self, 'channel') and self.channel:
            try:
                logger.info(f"Closing gRPC channel for {self.endpoint}")
                self.channel.close()
            except Exception as e:
                logger.debug(f"Error closing channel: {e}")
            finally:
                self.channel = None
        
        self.stream = None
        self.client = None
    
    def refresh_connection(self, subscription_request):
        """Manually refresh the gRPC connection"""
        logger.info("Manually refreshing gRPC connection...")
        self.clear_timers()
        self.cleanup_connection()
        self.is_reconnecting = False
        self.reconnect_attempts = 0
        
        if self.connect(subscription_request):
            logger.info("Connection refresh successful")
            # Start streaming in a separate thread
            stream_thread = threading.Thread(
                target=self.start_streaming, 
                args=[subscription_request],
                daemon=True,
                name="GrpcStreamThread"
            )
            stream_thread.start()
        else:
            logger.error("Connection refresh failed")
            self.schedule_reconnect(subscription_request)
    
    def shutdown(self):
        """Shutdown the stream manager"""
        logger.info("Shutting down gRPC stream manager")
        self.clear_timers()
        self.cleanup_connection()

def process_buffers(obj):
    """Convert all bytes objects to base58 strings, similar to TypeScript version"""
    if obj is None:
        return obj
    if isinstance(obj, bytes):
        return base58.b58encode(obj).decode()
    if isinstance(obj, list):
        return [process_buffers(item) for item in obj]
    if isinstance(obj, dict):
        return {k: process_buffers(v) for k, v in obj.items()}
    return obj

def process_transaction(msg):
    """
    Process a single transaction message.
    This function runs in a separate thread.
    """
    try:
        # Process all buffers/bytes to base58 strings first (like TypeScript version)
        processed_msg = process_buffers(msg)
        
        # Early return for invalid data structure
        if not hasattr(processed_msg, 'transaction'):
            return
            
        transaction = processed_msg.transaction
        if not hasattr(transaction, 'transaction') or not transaction.transaction:
            return
            
        tx_info = transaction.transaction
        if not hasattr(tx_info, 'transaction') or not tx_info.transaction:
            return
            
        inner_tx = tx_info.transaction
        if not hasattr(inner_tx, 'message') or not inner_tx.message:
            return
            
        # Get account keys - early return if none
        accountkeys = inner_tx.message.account_keys
        if not accountkeys:
            return
        
        # now do blacklist checking with raw bytes (fast!)
        # Short-circuit on first blacklisted account key
        for key in accountkeys:
            # Short-circuit: immediate return if this key is blacklisted
            if check_and_update_account_key_activity(key):
                return  # Skip transaction immediately - no need to check remaining keys
            
        # Early return for complex transactions (cheapest check first)
        if len(accountkeys) > 11:
            return
            
        # Early return if no meta data (cheap check)
        if not hasattr(tx_info, 'meta') or not tx_info.meta:
            return
            
        meta = tx_info.meta
        
        # Get token balances - early validation of structure (cheap checks)
        pretokenbalances = getattr(meta, 'pre_token_balances', [])
        posttokenbalances = getattr(meta, 'post_token_balances', [])
        
        # Early return for invalid token balance structure
        if (not pretokenbalances or not posttokenbalances or 
            len(pretokenbalances) > 2 or len(posttokenbalances) != 2 or 
            len(pretokenbalances) < 1):
            return
            
        # Early token validation (before expensive operations)
        # Check if all token mints are in our monitored list and are the same token
        mint_address = None
        
        # Check pre-token balances
        for balance in pretokenbalances:
            if not hasattr(balance, 'mint') or balance.mint not in MONITORED_TOKENS:
                return
            if mint_address is None:
                mint_address = balance.mint
            elif mint_address != balance.mint:
                return  # Mixed tokens, not a simple transfer
                
        # Check post-token balances
        for balance in posttokenbalances:
            if not hasattr(balance, 'mint') or balance.mint not in MONITORED_TOKENS:
                return
            if mint_address != balance.mint:
                return  # Mixed tokens, not a simple transfer
        
        # Validate token balance data structure before processing
        # Early return if any balance is missing required fields
        for balance in pretokenbalances:
            if (not hasattr(balance, 'owner') or not balance.owner or
                not hasattr(balance, 'ui_token_amount') or not balance.ui_token_amount or
                not hasattr(balance.ui_token_amount, 'ui_amount_string')):
                return
                
        for balance in posttokenbalances:
            if (not hasattr(balance, 'owner') or not balance.owner or
                not hasattr(balance, 'ui_token_amount') or not balance.ui_token_amount or
                not hasattr(balance.ui_token_amount, 'ui_amount_string')):
                return
        
        # Calculate balance changes for each owner
        balance_changes = {}
        
        # Process pre-token balances (subtract from owner's balance)
        for balance in pretokenbalances:
            owner = balance.owner  # Already converted to base58 string by process_buffers
            try:
                amount = float(balance.ui_token_amount.ui_amount_string)
            except (ValueError, TypeError):
                return  # Invalid amount format - skip transaction
            balance_changes[owner] = balance_changes.get(owner, 0) - amount
        
        # Process post-token balances (add to owner's balance)
        for balance in posttokenbalances:
            owner = balance.owner  # Already converted to base58 string by process_buffers
            try:
                amount = float(balance.ui_token_amount.ui_amount_string)
            except (ValueError, TypeError):
                return  # Invalid amount format - skip transaction
            balance_changes[owner] = balance_changes.get(owner, 0) + amount
        
        # Find sender (negative change) and receiver (positive change)
        sender = ''
        receiver = ''
        amount_sent = 0
        amount_received = 0
        
        for owner, change in balance_changes.items():
            if change < 0 and not sender:
                sender = owner
                amount_sent = abs(change)
            elif change > 0 and not receiver:
                receiver = owner
                amount_received = change
            # Short-circuit: early exit if both found
            if sender and receiver:
                break
        
        # Early return if can't identify sender/receiver or invalid amounts
        if not sender or not receiver or amount_sent <= 0 or amount_received <= 0:
            return
            
        # Early return for token-specific amount threshold (before expensive calculations)
        token_info = MONITORED_TOKENS[mint_address]
        min_transfer = token_info.get("min_transfer", 10)  # Default to 10 if not specified
        if amount_sent < min_transfer:
            return
            
        # Calculate discrepancy (only if we've passed other checks)
        discrepancy = abs(amount_sent - amount_received) / amount_sent
        
        # Early return for tolerance check
        if discrepancy > 0.04:
            return
            
        # Find sender's remaining balance (only if we've passed all other checks)
        sender_remaining_balance = 0
        for balance in posttokenbalances:
            owner = balance.owner  # Already converted to base58 string by process_buffers
            if owner == sender:
                try:
                    sender_remaining_balance = float(balance.ui_token_amount.ui_amount_string)
                except (ValueError, TypeError):
                    return  # Invalid balance format
                break
        
        # Final threshold check using token-specific minimum balance
        token_info = MONITORED_TOKENS[mint_address]
        min_balance = token_info["min_balance"]
        if sender_remaining_balance < min_balance:
            return
            
        # Get transaction signature (only for successful matches)
        signature = ''
        if hasattr(inner_tx, 'signatures') and inner_tx.signatures:
            signature = inner_tx.signatures[0]  # Already converted to base58 string by process_buffers
        
        # Account keys are already base58 strings from process_buffers
        account_keys_str = accountkeys
        
        # Get token info for logging
        token_info = MONITORED_TOKENS[mint_address]
        token_name = token_info["name"]
        
        # Log the successful token transfer detection
        logger.info(f"Transaction is a simple transfer of {token_name}")
        logger.info(f"Signature: {signature}")
        logger.info(f"{token_name} Transfer Details:")
        logger.info(f"  Token: {token_name} ({mint_address})")
        logger.info(f"  From: {sender}")
        logger.info(f"  To: {receiver}")
        logger.info(f"  Amount Sent: {amount_sent:.6f} {token_name}")
        logger.info(f"  Amount Received: {amount_received:.6f} {token_name}")
        logger.info(f"  Sender's Remaining Balance: {sender_remaining_balance:.6f} {token_name}")
        logger.info(f"  Discrepancy: {(discrepancy * 100):.2f}%")
        logger.info("Account keys in transaction:")
        
        # Call poison endpoint here (fire-and-forget)
        logger.info("calling poison endpoint on localhost:5001/poison")
        try:
            # Fire-and-forget HTTP request with persistent client
            poison_client.post('http://127.0.0.1:5001/poison', json={
                'detectedsender': sender,
                'detectedreceiver': receiver,
                'token': token_name,
                'mint_address': mint_address
            })
        except (httpx.TimeoutException, httpx.ConnectError, Exception):
            # Ignore all errors - fire and forget
            pass
             
    except Exception as e:
        logger.error(f"Error processing transaction: {e}")

def transaction_worker():
    """
    Worker thread that processes transactions from the queue.
    """
    while not shutdown_event.is_set():
        try:
            # Get transaction from queue with timeout
            msg = processing_queue.get(timeout=1)
            if msg is None:  # Shutdown signal
                break
                
            process_transaction(msg)
            processing_queue.task_done()
            
        except queue.Empty:
            continue  # Timeout, continue to check for shutdown
        except Exception as e:
            logger.error(f"Error in transaction worker: {e}")
    
    logger.info("Transaction worker shutting down")

def transaction_handler(msg):
    """
    Non-blocking transaction handler that queues messages for processing.
    """
    if shutdown_event.is_set():
        return  # Don't process new messages during shutdown
        
    try:
        # Try to add to queue (non-blocking)
        try:
            processing_queue.put_nowait(msg)
            logger.debug("Transaction queued for processing")
        except queue.Full:
            # Queue is full, drop the message and log with queue size info
            queue_size = processing_queue.qsize()
            logger.warning(f"Processing queue full ({queue_size}/{QUEUE_MAX_SIZE}), dropping transaction")
            
    except Exception as e:
        logger.error(f"Error in transaction handler: {e}")

def start_worker_threads():
    """
    Start the worker threads for processing transactions.
    """
    workers = []
    for i in range(MAX_WORKER_THREADS):
        worker = threading.Thread(target=transaction_worker, daemon=True, name=f"TransactionWorker-{i}")
        worker.start()
        workers.append(worker)
        logger.info(f"Started transaction worker thread {i}")
    return workers

# Create global stream manager instance
stream_manager: Optional[GrpcStreamManager] = None

def add_permanent_blacklist(wallet_address: str):
    """Add a wallet address to the permanent blacklist"""
    try:
        wallet_bytes = base58.b58decode(wallet_address)
        PERMANENTLY_BLACKLISTED_KEYS_BYTES.add(wallet_bytes)
        
        # Also add to regular blacklist if not already there
        with blacklist_lock:
            blacklisted_account_keys.add(wallet_bytes)
        save_blacklist()
        
        logger.info(f"Added {wallet_address} to permanent blacklist")
        return True
    except Exception as e:
        logger.error(f"Failed to add {wallet_address} to permanent blacklist: {e}")
        return False

def is_permanently_blacklisted(account_key_bytes: bytes) -> bool:
    """Check if an account key is permanently blacklisted"""
    return account_key_bytes in PERMANENTLY_BLACKLISTED_KEYS_BYTES

def list_permanent_blacklist():
    """List all permanently blacklisted addresses (for debugging/monitoring)"""
    logger.info("Permanently blacklisted addresses:")
    for key_bytes in PERMANENTLY_BLACKLISTED_KEYS_BYTES:
        address = base58.b58encode(key_bytes).decode()
        logger.info(f"  - {address}")
    return list(PERMANENTLY_BLACKLISTED_KEYS_BYTES)

def add_monitored_token(mint_address: str, name: str, min_balance: float, min_transfer: float = 10.0):
    """Add a new token to the monitoring list"""
    MONITORED_TOKENS[mint_address] = {
        "name": name,
        "min_balance": min_balance,
        "min_transfer": min_transfer
    }
    logger.info(f"Added {name} ({mint_address}) to monitored tokens with min balance {min_balance} and min transfer {min_transfer}")

def remove_monitored_token(mint_address: str):
    """Remove a token from the monitoring list"""
    if mint_address in MONITORED_TOKENS:
        token_name = MONITORED_TOKENS[mint_address]["name"]
        del MONITORED_TOKENS[mint_address]
        logger.info(f"Removed {token_name} ({mint_address}) from monitored tokens")
        return True
    return False

def list_monitored_tokens():
    """List all currently monitored tokens"""
    logger.info("Currently monitored tokens:")
    for mint_address, info in MONITORED_TOKENS.items():
        min_transfer = info.get('min_transfer', 10)  # Default to 10 if not specified
        logger.info(f"  - {info['name']}: {mint_address} (min balance: {info['min_balance']}, min transfer: {min_transfer})")
    return MONITORED_TOKENS.copy()

def refresh_grpc_connection():
    """Manually refresh the gRPC connection (useful for debugging)"""
    global stream_manager
    if stream_manager:
        grpcFilter = {
            "filter": pb_pb2.SubscribeRequestFilterTransactions(
                account_include=[TOKEN_PROGRAM_ID],
                failed=False
            )
        }
        subscription = pb_pb2.SubscribeRequest(
            transactions=grpcFilter,
            commitment=pb_pb2.CommitmentLevel.CONFIRMED
        )
        stream_manager.refresh_connection(subscription)
        logger.info("Manual gRPC connection refresh triggered")
    else:
        logger.warning("Stream manager not initialized, cannot refresh connection")

def signal_handler(sig, frame):
    """Handle interrupt signals gracefully"""
    logger.info(f"Received signal {sig}, initiating shutdown...")
    shutdown_event.set()

def main():
    global stream_manager
    
    logger.info("Starting multithreaded transaction monitor with account key blacklisting and robust gRPC connection...")
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # List monitored tokens
    list_monitored_tokens()
    
    # Initialize permanent blacklist
    initialize_permanent_blacklist()
    
    # Load existing blacklist on startup
    load_blacklist()
    
    # Start worker threads
    workers = start_worker_threads()
    logger.info(f"Started {len(workers)} worker threads")
    
    # Start periodic sweep for unblacklisting
    sweep_thread = start_periodic_sweep()

    # Create subscription request
    grpcFilter = {
        "filter": pb_pb2.SubscribeRequestFilterTransactions(
            account_include=[TOKEN_PROGRAM_ID],
            failed=False
        )
    }
    subscription = pb_pb2.SubscribeRequest(
        transactions=grpcFilter,
        commitment=pb_pb2.CommitmentLevel.CONFIRMED
    )

    # Initialize stream manager
    stream_manager = GrpcStreamManager(
        endpoint=node["url"],
        auth_token=node.get("grpcToken", ""),
        data_handler=transaction_handler
    )

    try:
        # Start initial connection
        if stream_manager.connect(subscription):
            logger.info("Initial gRPC connection successful")
            # Start streaming in a separate thread so main thread can handle reconnections
            stream_thread = threading.Thread(
                target=stream_manager.start_streaming, 
                args=[subscription],
                daemon=True,
                name="InitialGrpcStreamThread"
            )
            stream_thread.start()
        else:
            logger.error("Failed to establish initial gRPC connection, starting reconnection process")
            # Start reconnection process
            stream_manager.schedule_reconnect(subscription)
            
        # Keep main thread alive until shutdown
        while not shutdown_event.is_set():
            time.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt, shutting down...")
        shutdown_event.set()
    except Exception as e:
        logger.error(f"Unexpected error in main: {e}")
        shutdown_event.set()
    
    # Shutdown sequence
    logger.info("Initiating shutdown sequence...")
    
    # Shutdown stream manager
    if stream_manager:
        stream_manager.shutdown()
    
    # Signal workers to shutdown by putting None messages
    for _ in range(MAX_WORKER_THREADS):
        try:
            processing_queue.put_nowait(None)
        except queue.Full:
            pass  # Queue is full, workers will see shutdown_event
    
    # Wait for queue to be processed with timeout
    logger.info("Waiting for processing queue to empty...")
    start_time = time.time()
    timeout = 10  # 10 seconds timeout
    
    while not processing_queue.empty() and (time.time() - start_time) < timeout:
        time.sleep(0.1)
    
    if not processing_queue.empty():
        logger.warning(f"Queue not empty after {timeout}s timeout, forcing shutdown")
    
    # Close HTTP client
    try:
        poison_client.close()
        logger.info("Closed HTTP client")
    except Exception as e:
        logger.warning(f"Error closing HTTP client: {e}")
    
    logger.info("Shutdown complete")

if __name__ == "__main__":
    main()
