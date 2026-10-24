# Running Curio's model on the cluster

Curio itself always runs on your Windows PC (it needs your screen, mic and
keyboard). Only the vision LLM runs on the cluster's H200. Whisper and the
voice run on the PC.

```
Windows PC                                   Cluster
┌──────────────────────┐   VPN + SSH    ┌───────────┐     ┌────────────────────┐
│ Curio            │ ─────────────► │ login     │ ──► │ compute node (H200)│
│  → localhost:8000 ───┼── tunnel ──────┼───────────┼───► │ vLLM 127.0.0.1:8000│
└──────────────────────┘                └───────────┘     └────────────────────┘
```

Replace `you` with your cluster username and `login.cluster.edu` with the
login node's hostname throughout.

## One-time setup

### 1. SSH key and config on Windows (PowerShell)

Windows 10/11 ships OpenSSH, so no extra install is needed.

```powershell
ssh-keygen -t ed25519            # press Enter through the prompts
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh you@login.cluster.edu "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

Then create `C:\Users\<you>\.ssh\config` (no file extension):

```
Host cluster
    HostName login.cluster.edu
    User you
    ServerAliveInterval 30

# Any compute node, reached through the login node.
Host gpu-*
    User you
    ProxyJump cluster
```

Change `gpu-*` to match your cluster's node names (whatever `squeue` shows,
for example `a100-03` → `Host a100-*`). Now `ssh cluster` logs you in.

### 2. Install vLLM on the cluster

```bash
ssh cluster
tmux new -s curio                     # survives VPN drops; reattach: tmux a -t curio

mkdir -p ~/curio/logs
# module load python/3.11 cuda/12.4    # if your cluster uses modules
python3 -m venv ~/curio/venv
source ~/curio/venv/bin/activate
pip install --upgrade pip && pip install "vllm>=0.11"   # Qwen3-VL needs 0.11+
```

### 3. Download the model to scratch storage (~66 GB)

Home directories usually have small quotas, so use scratch or project space:

```bash
export HF_HOME=/path/to/your/scratch/hf
hf download Qwen/Qwen3-VL-32B-Instruct
```

### 4. Create an API key

On a shared cluster, other users can reach ports on the node you're on.
The key keeps them from using your model:

```bash
openssl rand -hex 16 > ~/curio/api_key && chmod 600 ~/curio/api_key
cat ~/curio/api_key                    # copy this for config.toml
```

### 5. Copy and edit the job script

From PowerShell in this repo:

```powershell
scp server\vllm.sbatch cluster:~/curio/
```

Edit `~/curio/vllm.sbatch` on the cluster: fill in every `CHANGE_ME`
(partition, account, and the same `HF_HOME` as step 3) and any `module load`
lines. Ask your cluster admins or check their docs if you're unsure of the
partition or GPU request syntax.

### 6. Point Curio at it

```powershell
cd curio-py
uv sync --extra local
```

In `%APPDATA%\Curio\config.toml`:

```toml
backend = "local"

[local]
llm_base_url = "http://localhost:8000/v1"
llm_model = "Qwen/Qwen3-VL-32B-Instruct"
llm_api_key = "<the key from step 4>"
point_coords = "norm1000"
```

## Every session

**1. Connect FortiClient VPN.**

**2. Start the model** (in tmux on the login node):

```bash
ssh cluster
tmux a -t curio || tmux new -s curio
cd ~/curio && sbatch vllm.sbatch
squeue --me                       # wait for state R, note the NODELIST
tail -f logs/vllm-<jobid>.out     # wait for "Application startup complete"
```

The first start takes a few minutes while the weights load onto the GPU.
The job keeps running if you close the terminal; it stops at its `--time`
limit or when you run `scancel <jobid>`.

**3. Open the tunnel** (new PowerShell window, leave it open):

```powershell
ssh -N -L 8000:localhost:8000 gpu-07      # the node from squeue
```

It prints nothing while it's working. Check it from another window:

```powershell
curl.exe -H "Authorization: Bearer <key>" http://localhost:8000/v1/models
```

**4. Run Curio:**

```powershell
cd curio-py
uv run python -m curio
```

**When you're done:** `scancel <jobid>` so you aren't holding a GPU others
could use.

## Troubleshooting

- **"cannot reach LLM server … is the VPN up and the SSH tunnel running?"**
  The VPN dropped, the tunnel window closed, or the job ended. Check
  `squeue --me`, then reopen the tunnel.
- **SSH to the compute node is refused.** Some clusters block it. Change
  `--host 127.0.0.1` to `--host 0.0.0.0` in `vllm.sbatch` and tunnel through
  the login node instead: `ssh -N -L 8000:gpu-07:8000 cluster`. The API key
  matters more in that setup, so don't skip it.
- **"address already in use" in the job log.** Someone else on the node has
  port 8000. Submit with another port, `PORT=8123 sbatch vllm.sbatch`, and
  tunnel `-L 8000:localhost:8123`.
- **Out of GPU memory.** Lower `--max-model-len` to 16384, or serve the
  faster MoE model instead: `MODEL=Qwen/Qwen3-VL-30B-A3B-Instruct sbatch vllm.sbatch`
  (also change `llm_model` in config.toml).
- **Pointing is consistently offset.** Check `point_coords` matches the model:
  `norm1000` for Qwen3-VL, `pixel` for Qwen2.5-VL.
