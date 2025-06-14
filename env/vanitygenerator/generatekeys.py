import logging
import multiprocessing
from multiprocessing.pool import Pool
from typing import List, Optional, Tuple, Dict

from core.config import DEFAULT_ITERATION_BITS, HostSetting
from core.opencl.manager import (
    get_all_gpu_devices,
    get_chosen_devices,
)
from core.searcher import multi_gpu_init, save_result
from core.utils.helpers import check_character, load_kernel_source
from core.utils.crypto import get_public_key_from_private_bytes
from base58 import b58encode
from nacl.signing import SigningKey

logging.basicConfig(level="INFO", format="[%(levelname)s %(asctime)s] %(message)s")


def generate_similar_address(wallet_address: str, use_gpu_selection: bool = False, force_gpu_0: bool = False) -> Dict[str, str]:
    """
    Generate a new Solana address that starts with the same 4 characters as the input address.
    
    Args:
        wallet_address (str): The input wallet address to match the first 4 characters
        use_gpu_selection (bool): Whether to manually select GPU devices
        force_gpu_0 (bool): If True, forces the use of GPU 0 (NVIDIA GPU)
        
    Returns:
        Dict[str, str]: Dictionary containing 'private_key_array', 'private_key_hex', 'public_key', etc.
    """
    if len(wallet_address) < 4:
        raise ValueError("Wallet address must be at least 4 characters long")
    
    # Extract first 4 characters from the input address
    starts_with = wallet_address[:4]
    
    # Validate the characters
    check_character("starts_with", starts_with)
    
    # Set up devices
    chosen_devices: Optional[Tuple[int, List[int]]] = None
    if force_gpu_0:
        # Force use of GPU 0 (typically NVIDIA)
        chosen_devices = (0, [0])  # Platform 0, Device 0
        gpu_counts = 1
        logging.info("Forcing use of GPU 0 (NVIDIA GPU)")
    elif use_gpu_selection:
        chosen_devices = get_chosen_devices()
        gpu_counts = len(chosen_devices[1])
    else:
        gpu_counts = len(get_all_gpu_devices())

    logging.info(f"Generating address starting with: {starts_with}")
    logging.info(f"Using {gpu_counts} OpenCL device(s)")

    with multiprocessing.Manager() as manager:
        with Pool(processes=gpu_counts) as pool:
            kernel_source = load_kernel_source(
                [starts_with], "", True  # case sensitive
            )
            lock = manager.Lock()
            stop_flag = manager.Value("i", 0)
            
            results = pool.starmap(
                multi_gpu_init,
                [
                    (
                        x,
                        HostSetting(kernel_source, DEFAULT_ITERATION_BITS),
                        gpu_counts,
                        stop_flag,
                        lock,
                        chosen_devices,
                    )
                    for x in range(gpu_counts)
                ],
            )
            
            # Process results and return the first valid keypair
            for result in results:
                if result and len(result) > 1 and result[0]:  # result[0] indicates success
                    # Extract private key bytes (result[1:] contains the private key)
                    pv_bytes = bytes(result[1:33])  # Private key is 32 bytes
                    
                    # Generate the signing key and public key
                    signing_key = SigningKey(pv_bytes)
                    pb_bytes = bytes(signing_key.verify_key)
                    public_key = b58encode(pb_bytes).decode()
                    
                    # Create the full 64-byte private key (private + public)
                    full_private_key = pv_bytes + pb_bytes
                    
                    logging.info(f"Generated keypair - Public key: {public_key}")
                    
                    return {
                        'private_key_array': list(full_private_key),  # 64-byte array for wallets
                        'private_key_hex': full_private_key.hex(),    # Hex format
                        'private_key_base58': b58encode(pv_bytes).decode(),  # Just the 32-byte private key
                        'public_key': public_key,
                        'raw_private_bytes': list(pv_bytes)  # Just the 32-byte private key
                    }
            
            raise RuntimeError("Failed to generate a matching address")


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn")
    
    # Example usage - force use of GPU 0 (NVIDIA GPU)
    example_address = "RAPELos1e9qSs2u7TsThXqkBSRVFxhmYaFKFZ1waUdcQ"
    result = generate_similar_address(example_address, force_gpu_0=True)
    print(f"Original address: {example_address}")
    print(f"Generated keypair:")
    print(f"  Public key:  {result['public_key']}")
    print(f"  Private key (64-byte array): {result['private_key_array']}")
    print(f"  Private key (hex): {result['private_key_hex']}")
    print(f"  Private key (base58): {result['private_key_base58']}")
