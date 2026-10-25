# Model server (lab GPU workstations)

Curio runs on your Windows laptop. Only the vision LLM runs here, on one
GPU of a shared lab workstation, behind an SSH tunnel. Whisper (speech-to-text)
and the voice still run on the laptop.

```
Windows laptop                             Lab workstation (no scheduler)
┌───────────────────────┐   VPN + SSH    ┌────────────────────────────┐
│ Curio             │ ─────────────► │ vLLM on one GPU            │
│  → localhost:8000 ────┼── tunnel ──────┼─► 127.0.0.1:8000 + API key │
└───────────────────────┘                └────────────────────────────┘
```

These machines are **standalone workstations, not a Slurm cluster**: there's no
queue. You start vLLM directly on a GPU you're allowed to use, and only when
nobody else is on it.

| Machine | GPUs | Ours to use | CUDA driver |
|---|---|---|---|
| `ece-cnc197130s.coeit.osu.edu` | 4× H100 NVL, 94 GB | **3** | 555 (CUDA 12.5) |
| `ece-drf95318s.coeit.osu.edu` | 8× H200 NVL, 141 GB | **4–7** | 580 (CUDA 13.0) |

Other lab members' jobs run on the rest, and they sometimes spread onto ours.
Always check before starting (`./gpu_status.sh`), and stop the server when
you're done so the card is free again.

## Files

| File | What it does |
|---|---|
| `curio.env.example` | Per-machine settings: allowed GPUs, venv, model path, ports. Copy to `curio.env`. |
| `common.sh` | Shared helpers (GPU idle checks). Sourced by the others. |
| `gpu_status.sh` | Table of your GPUs: memory, utilization, owners, idle yes/no. Exit 0 if one is idle. |
| `serve.sh [gpu]` | Starts vLLM on an idle allowed GPU. Refuses busy or disallowed GPUs, checks every weight shard first. `DRY_RUN=1` prints the command only. |
| `wait_and_serve.sh` | Checks every 60 s and starts `serve.sh` as soon as a GPU is idle. |
| `test_vision.sh` | Sends a picture with a red SAVE button and checks the model points at it in the 0–1000 format. Prints PASS/FAIL. |

## One-time setup on a machine

Everything here uses standard tools and needs no sudo.

1. **Pick folders.** Put weights and the venv somewhere with room; on
   ece-cnc197130s `/local/scratch` only has ~20 GB usable, so we use the home
   network drive (`~/curio-models`). Logs, temp files and the API key go in
   `/local/scratch/$USER/Project26/curio`.

2. **Get the scripts:**
   ```bash
   git clone https://github.com/krishdeshmukhhh/Hack26.git ~/Hack26
   cd ~/Hack26/server
   cp curio.env.example curio.env    # then edit: ALLOWED_GPUS, paths
   ```

3. **Create a venv with vLLM ≥ 0.11** (Qwen3-VL needs it). Keep pip's cache
   off your home drive:
   ```bash
   python3 -m venv ~/curio-models/venv
   source ~/curio-models/venv/bin/activate
   PIP_CACHE_DIR=/local/scratch/$USER/pip-cache pip install "vllm>=0.11"
   ```
   On ece-cnc197130s the combination that works is **vLLM 0.11.0, torch
   2.8.0 (cu128), transformers 4.57.1, Python 3.12**. The CUDA 12.8 wheels run
   on its 12.5 driver through CUDA minor-version compatibility. Pin
   `transformers==4.57.1`; newer versions break vLLM 0.11.0.

   Quick GPU check before loading a model:
   ```bash
   CUDA_VISIBLE_DEVICES=3 python -c "import torch; x=torch.randn(4096,4096,device='cuda'); print(torch.version.cuda, (x@x).sum().item())"
   ```

4. **Download the weights (~32 GB):**
   ```bash
   HF_HOME=~/curio-models/hf-cache hf download Qwen/Qwen3-VL-30B-A3B-Instruct-FP8 \
       --local-dir ~/curio-models/Qwen3-VL-30B-A3B-Instruct-FP8
   ```

5. **Create the API key.** Other users on the machine can reach its localhost
   ports, so the server requires a key:
   ```bash
   mkdir -p /local/scratch/$USER/Project26/curio
   openssl rand -hex 16 > /local/scratch/$USER/Project26/curio/api_key
   chmod 600 /local/scratch/$USER/Project26/curio/api_key
   ```
   Put the same key in the laptop's `config.toml` as `llm_api_key`. Don't
   commit it or paste it into shared chats.

6. **Check:** `./gpu_status.sh` and `DRY_RUN=1 ./serve.sh`. With a free GPU,
   the only output should be the GPU, the port and the command.

## Every session

See [`docs/RUNNING.md`](../docs/RUNNING.md) for the full laptop + server
walkthrough. Server side only:

```bash
cd ~/Hack26/server
./gpu_status.sh                                  # is one of our GPUs idle?
tmux new -d -s curio "$PWD/serve.sh"            # or "$PWD/serve.sh 3" for a specific GPU
tail -f "$(ls -t /local/scratch/$USER/Project26/curio/logs/vllm-*.log | head -1)"
# wait for "Application startup complete" (3-6 min; longer from a network drive)
./test_vision.sh                                 # should print PASS
```

Stop it when you're done: `tmux kill-session -t curio`.

No free GPU? `tmux new -d -s curio "$PWD/wait_and_serve.sh"` starts it the
moment one frees up. Mind the clock: it'll hold the card until you stop it.

## Latency tuning

`curio.env` has `ENABLE_PREFIX_CACHING` (default 1, explicit
`--enable-prefix-caching`; already on by default in vLLM 0.11), plus optional,
empty-by-default `MAX_NUM_SEQS` and `MM_PROCESSOR_KWARGS`. Chunked prefill is
already on in the V1 engine. Changes need a server restart. Check the log for
"Prefix cache hit rate" rising after the second request.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Crash right after weights load: `NVCC version must be at least 12.9` | DeepGEMM compiles FP8 kernels with the system CUDA compiler, which is too old here. `serve.sh` sets `VLLM_USE_DEEP_GEMM=0`; make sure any hand-written launch does too. |
| `GPU N is busy; refusing to start` | Someone else is on it. Check `./gpu_status.sh`, wait, or use `wait_and_serve.sh`. |
| Out of memory at startup | The GPU isn't as free as it looked, or the model is too big for the card. Lower `GPU_MEM_UTIL` or `MAX_MODEL_LEN` in `curio.env`. |
| `address already in use` | `serve.sh` already moves to the next free port and prints it. Tunnel to that port: `-L 8000:localhost:<port>`. |
| Laptop says "cannot reach LLM server" | VPN down, tunnel window closed, or the server stopped. `tmux ls` on the server shows whether it's still running. |
| Tunnel window prints `channel 2: open failed: connect failed: Connection refused` | The tunnel is fine but nothing is listening yet. The server is still loading or has crashed; check its log. |
| `test_vision.sh` FAILs with a POINT far off | Coordinate format mismatch. Qwen3-VL uses 0–1000 (`point_coords = "norm1000"`); Qwen2.5-VL uses pixels (`"pixel"`). |
