import logging
import threading
import time
from typing import Dict, Optional
from core.config import DEFAULT_ITERATION_BITS, HostSetting
from core.opencl.manager import get_all_gpu_devices, get_chosen_devices
from core.searcher import Searcher
from core.utils.helpers import check_character, load_kernel_source
from base58 import b58encode
from nacl.signing import SigningKey

logging.basicConfig(level="INFO", format="[%(levelname)s %(asctime)s] %(message)s")


class PersistentVanityGenerator:
    """
    A persistent vanity generator that maintains GPU contexts for reuse.
    GPU contexts are kept alive for 20 minutes and reused across multiple generation requests.
    """
    
    def __init__(self, force_gpu_0: bool = True, context_timeout: int = 1200):  # 20 minutes default
        self.force_gpu_0 = force_gpu_0
        self.context_timeout = context_timeout
        self.searchers = {}
        self.last_used = {}
        self.lock = threading.Lock()
        self.cleanup_thread = None
        self.start_cleanup_thread()
    
    def start_cleanup_thread(self):
        """Start the background thread that cleans up expired GPU contexts."""
        def cleanup_worker():
            while True:
                time.sleep(60)  # Check every minute
                with self.lock:
                    current_time = time.time()
                    expired_keys = []
                    for key, last_use_time in self.last_used.items():
                        if current_time - last_use_time > self.context_timeout:
                            expired_keys.append(key)
                    
                    for key in expired_keys:
                        if key in self.searchers:
                            logging.info(f"Cleaning up expired GPU context for pattern: {key}")
                            del self.searchers[key]
                            del self.last_used[key]
        
        self.cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
        self.cleanup_thread.start()
    
    def get_or_create_searcher(self, starts_with: str) -> Searcher:
        """Get existing searcher or create new one for the given pattern."""
        with self.lock:
            current_time = time.time()
            
            # Check if we have a valid searcher for this pattern
            if starts_with in self.searchers:
                if current_time - self.last_used[starts_with] < self.context_timeout:
                    self.last_used[starts_with] = current_time
                    logging.info(f"Reusing existing GPU context for pattern: {starts_with}")
                    return self.searchers[starts_with]
                else:
                    # Context expired, remove it
                    logging.info(f"GPU context expired for pattern: {starts_with}, creating new one")
                    del self.searchers[starts_with]
                    del self.last_used[starts_with]
            
            # Create new searcher
            logging.info(f"Creating new GPU context for pattern: {starts_with}")
            kernel_source = load_kernel_source([starts_with], "", True)
            setting = HostSetting(kernel_source, DEFAULT_ITERATION_BITS)
            
            chosen_devices = None
            if self.force_gpu_0:
                chosen_devices = (0, [0])  # Platform 0, Device 0
                device_index = 0
            else:
                device_index = 0  # Use first available device
            
            searcher = Searcher(
                kernel_source=setting.kernel_source,
                index=device_index,
                setting=setting,
                chosen_devices=chosen_devices,
            )
            
            self.searchers[starts_with] = searcher
            self.last_used[starts_with] = current_time
            
            return searcher
    
    def generate_similar_address(self, wallet_address: str) -> Dict[str, str]:
        """
        Generate a new Solana address that starts with the same 4 characters as the input address.
        Uses persistent GPU contexts that are reused for 20 minutes.
        
        Args:
            wallet_address (str): The input wallet address to match the first 4 characters
            
        Returns:
            Dict[str, str]: Dictionary containing 'private_key_array', 'private_key_hex', 'public_key', etc.
        """
        if len(wallet_address) < 4:
            raise ValueError("Wallet address must be at least 4 characters long")
        
        # Extract first 4 characters from the input address
        starts_with = wallet_address[:4]
        
        # Validate the characters
        check_character("starts_with", starts_with)
        
        logging.info(f"Generating address starting with: {starts_with}")
        
        # Get or create searcher for this pattern
        searcher = self.get_or_create_searcher(starts_with)
        
        # Search for matching address
        max_attempts = 1000  # Prevent infinite loops
        attempts = 0
        
        while attempts < max_attempts:
            result = searcher.find(log_stats=(attempts == 0))  # Log stats only on first attempt
            
            if result[0]:  # Found a match
                # Extract private key bytes (result[1:33] contains the private key)
                pv_bytes = bytes(result[1:33])  # Private key is 32 bytes
                
                # Generate the signing key and public key
                signing_key = SigningKey(pv_bytes)
                pb_bytes = bytes(signing_key.verify_key)
                public_key = b58encode(pb_bytes).decode()
                
                # Create the full 64-byte private key (private + public)
                full_private_key = pv_bytes + pb_bytes
                
                logging.info(f"Generated keypair after {attempts + 1} attempts - Public key: {public_key}")
                
                return {
                    'private_key_array': list(full_private_key),  # 64-byte array for wallets
                    'private_key_hex': full_private_key.hex(),    # Hex format
                    'private_key_base58': b58encode(pv_bytes).decode(),  # Just the 32-byte private key
                    'public_key': public_key,
                    'raw_private_bytes': list(pv_bytes)  # Just the 32-byte private key
                }
            
            attempts += 1
        
        raise RuntimeError(f"Failed to generate a matching address after {max_attempts} attempts")


# Global instance
_persistent_generator = None
_generator_lock = threading.Lock()


def get_persistent_generator() -> PersistentVanityGenerator:
    """Get the global persistent vanity generator instance."""
    global _persistent_generator
    with _generator_lock:
        if _persistent_generator is None:
            _persistent_generator = PersistentVanityGenerator(force_gpu_0=True)
        return _persistent_generator


def generate_similar_address_persistent(wallet_address: str) -> Dict[str, str]:
    """
    Generate a similar address using the persistent GPU context.
    This is a drop-in replacement for the original generate_similar_address function.
    """
    generator = get_persistent_generator()
    return generator.generate_similar_address(wallet_address)


if __name__ == "__main__":
    # Test the persistent generator
    example_address = "RAPELos1e9qSs2u7TsThXqkBSRVFxhmYaFKFZ1waUdcQ"
    
    generator = PersistentVanityGenerator(force_gpu_0=True)
    
    print("Testing persistent vanity generator...")
    start_time = time.time()
    
    # Generate first address
    result1 = generator.generate_similar_address(example_address)
    first_gen_time = time.time() - start_time
    print(f"First generation took {first_gen_time:.2f} seconds")
    print(f"Generated: {result1['public_key']}")
    
    # Generate second address (should reuse GPU context)
    start_time = time.time()
    result2 = generator.generate_similar_address(example_address)
    second_gen_time = time.time() - start_time
    print(f"Second generation took {second_gen_time:.2f} seconds")
    print(f"Generated: {result2['public_key']}")
    
    print(f"Speed improvement: {(first_gen_time - second_gen_time) / first_gen_time * 100:.1f}%") 