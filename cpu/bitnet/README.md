# BitNet b1.58 (1-bit) CPU stress

Uses Microsoft [BitNet](https://github.com/microsoft/BitNet) (`bitnet.cpp`) with
`BitNet-b1.58-2B-4T` I2_S GGUF and its built `llama-server` (OpenAI-compatible).

## Start (port 8011)

```bash
cd /root/.cvr/llm_stress_test/cpu
./commands.sh stop_llama   # free CPU if Q4 llama is on 8010

BIN=bitnet/microsoft-BitNet/build/bin
MODEL=bitnet/microsoft-BitNet/models/BitNet-b1.58-2B-4T/ggml-model-i2_s.gguf
export LD_LIBRARY_PATH="$PWD/$BIN:$LD_LIBRARY_PATH"
NPROC=$(nproc)
nohup "$BIN/llama-server" \
  --model "$MODEL" --alias BitNet-b1.58-2B-4T \
  --host 0.0.0.0 --port 8011 \
  --threads "$NPROC" --threads-batch "$NPROC" \
  --parallel 4 --ctx-size $((4096*4)) --n-gpu-layers 0 \
  > bitnet.log 2>&1 & echo $! > bitnet.pid
```

Results: `compare_bitnet_4c.json`, `compare_bitnet_find_limit.json`.
