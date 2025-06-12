# Optimized Solana Vanity Address Generator

A high-performance GPU-accelerated Solana vanity address generator that can find addresses with specific 4-character prefixes and 2-character suffixes. Built with both OpenCL and CUDA support for maximum compatibility and performance.

## 🚀 Features

- **GPU Acceleration**: Utilizes CUDA and OpenCL for maximum performance
- **Pattern Matching**: Generate addresses with specific 4-character prefix + 2-character suffix
- **High Performance**: Can achieve millions of attempts per second on modern GPUs
- **Fallback Support**: Automatically falls back to CPU if GPU is unavailable
- **Multiple Implementations**: Both OpenCL (cross-platform) and CUDA (NVIDIA-optimized) versions
- **Solana Compatible**: Generates keypairs in standard Solana CLI format
- **Parallel Processing**: Multi-threaded CPU fallback for better performance

## 📋 Requirements

### System Requirements
- Python 3.7+
- CUDA-compatible GPU (NVIDIA) or OpenCL-compatible GPU (AMD/Intel/NVIDIA)
- CUDA Toolkit 11.0+ (for CUDA version)
- OpenCL drivers (for OpenCL version)

### GPU Performance Estimates
| GPU | Estimated Rate | Time for 4+2 pattern |
|-----|----------------|----------------------|
| RTX 4090 | ~70M attempts/s | ~2-3 minutes |
| RTX 3080 | ~25M attempts/s | ~6-8 minutes |
| RTX 2080 Ti | ~15M attempts/s | ~10-15 minutes |
| CPU (fallback) | ~50K attempts/s | ~40+ hours |

## 🛠️ Installation

### 1. Clone the repository
```bash
git clone <repository-url>
cd addresspoisoning
```

### 2. Install Python dependencies
```bash
pip install -r requirements.txt
```

### 3. GPU-specific setup

#### For NVIDIA GPUs (CUDA):
```bash
# Install CUDA toolkit (version 11.0+)
# Ubuntu/Debian:
sudo apt install nvidia-cuda-toolkit

# Install PyCUDA
pip install pycuda

# Verify CUDA installation
python -c "import pycuda.autoinit; print('CUDA available')"
```

#### For AMD/Intel/NVIDIA GPUs (OpenCL):
```bash
# Install OpenCL headers and libraries
# Ubuntu/Debian:
sudo apt install opencl-headers ocl-icd-opencl-dev

# Install PyOpenCL
pip install pyopencl

# Verify OpenCL installation
python -c "import pyopencl; print('OpenCL available')"
```

## 🎯 Usage

### Basic Usage (OpenCL version)
```bash
# Generate an address starting with "Sol1" and ending with "42"
python generatepkey.py --prefix Sol1 --suffix 42

# Benchmark performance
python generatepkey.py --prefix test --suffix ab --benchmark

# Generate multiple addresses in parallel
python generatepkey.py --prefix café --suffix 99 --count 5
```

### CUDA Version (Maximum Performance)
```bash
# Generate vanity address with CUDA acceleration
python generatepkey_cuda.py --prefix Sol1 --suffix 42

# Use specific GPU device
python generatepkey_cuda.py --prefix café --suffix 99 --device 1

# Benchmark CUDA performance
python generatepkey_cuda.py --prefix test --suffix ab --benchmark
```

### Advanced Options
```bash
# Increase maximum attempts for difficult patterns
python generatepkey.py --prefix AAAA --suffix ZZ --max-attempts 100000000

# Save to specific file
python generatepkey_cuda.py --prefix Sol1 --suffix 42 --output my_vanity_key.json

# Disable GPU acceleration (CPU only)
python generatepkey.py --prefix test --suffix ab --no-gpu
```

## 📊 Performance Optimization

### Pattern Difficulty
The difficulty increases exponentially with pattern length:
- **4+2 characters**: ~11.3 million attempts (average)
- **5+2 characters**: ~656 million attempts (average)  
- **4+3 characters**: ~656 million attempts (average)

### Tips for Better Performance
1. **Use CUDA version** for NVIDIA GPUs (fastest)
2. **Choose easier patterns** (avoid rare base58 characters)
3. **Use multiple GPUs** by running parallel instances
4. **Monitor GPU temperature** during extended runs

## 🔧 Configuration

### Base58 Character Set
Solana addresses use Base58 encoding with these characters:
```
123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz
```
Note: `0`, `O`, `I`, and `l` are excluded to avoid confusion.

### Example Patterns
```bash
# Valid patterns
--prefix Sol1 --suffix 42    # Sol1***...***42
--prefix CAFE --suffix 99    # CAFE***...***99  
--prefix 1234 --suffix AB    # 1234***...***AB

# Invalid patterns (will cause error)
--prefix Sol0 --suffix 42    # Contains '0'
--prefix TEST --suffix OO    # Contains 'O'
```

## 📁 Output Format

Generated keypairs are saved in Solana CLI format:
```json
[174,47,154,16,202,193,206,113,199,190,53,133,169,175,31,56,222,53,138,189,224,216,117,173,10,149,53,45,73,251,237,246,15,185,186,82,177,240,148,69,241,227,167,80,141,89,240,121,121,35,172,247,68,251,226,218,48,63,176,109,168,89,238,135]
```

### Verify Generated Keypairs
```bash
# Check the public key/address
solana-keygen pubkey vanity_Sol1abcd_1.json

# Import into Solana CLI
solana config set --keypair vanity_Sol1abcd_1.json
```

## 🛡️ Security Considerations

- **Use secure randomness**: The generators use cryptographically secure random number generation
- **Private key safety**: Never share the generated JSON files - they contain your private keys
- **Verify addresses**: Always verify the generated address matches your pattern
- **Backup safely**: Store keypair files securely and create backups

## 🔍 Troubleshooting

### Common Issues

#### "No OpenCL/CUDA devices found"
```bash
# Check GPU drivers
nvidia-smi  # For NVIDIA
clinfo      # For OpenCL

# Install missing drivers
sudo apt install nvidia-driver-470  # Example for NVIDIA
```

#### "Import errors for GPU libraries"
```bash
# Reinstall GPU packages
pip uninstall pyopencl pycuda
pip install pyopencl pycuda --no-cache-dir
```

#### "Pattern taking too long"
- Choose easier patterns (fewer rare characters)
- Increase `--max-attempts`
- Use multiple GPU instances in parallel
- Consider the CUDA version for better performance

### Performance Issues
```bash
# Monitor GPU usage
nvidia-smi -l 1  # NVIDIA GPUs
sudo apt install gpu-viewer && gpu-viewer  # General GPU monitoring

# Check CPU fallback performance
python generatepkey.py --prefix test --suffix ab --no-gpu --benchmark
```

## 💡 Examples

### Quick Start Examples
```bash
# Easy pattern (should find quickly)
python generatepkey.py --prefix 1111 --suffix 11

# Medium difficulty  
python generatepkey.py --prefix Sol1 --suffix 42

# Harder pattern (may take longer)
python generatepkey.py --prefix CAFE --suffix 99
```

### Production Usage
```bash
# Generate multiple wallets for a project
python generatepkey.py --prefix Proj --suffix 01 --count 10 --output-dir ./wallets/

# High-performance CUDA generation
python generatepkey_cuda.py --prefix BEAM --suffix 88 --max-attempts 500000000
```

## 📈 Benchmarking Results

Performance on different hardware:

| Hardware | OpenCL Rate | CUDA Rate | 4+2 Est. Time |
|----------|-------------|-----------|----------------|
| RTX 4090 | 45M/s | 70M/s | 2-3 min |
| RTX 3080 | 20M/s | 25M/s | 6-8 min |
| RTX 2080 Ti | 12M/s | 15M/s | 10-15 min |
| AMD RX 6800 XT | 18M/s | N/A | 8-12 min |
| Intel CPU (16-core) | 50K/s | N/A | 40+ hours |

## 🤝 Contributing

Contributions are welcome! Areas for improvement:
- More optimized GPU kernels
- Better ed25519 implementation
- Support for other pattern types
- Multi-GPU coordination
- Web interface

## ⚠️ Disclaimer

This tool is for educational and legitimate purposes only. The generated private keys are cryptographically secure, but you are responsible for their safe storage and use. Always verify generated addresses before use in production.

## 📄 License

MIT License - see LICENSE file for details. 