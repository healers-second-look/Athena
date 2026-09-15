# Self-Hosted LLM Backend: BioMistral-7B

Issue #122: an open-source, self-hostable medical LLM backend powering
synthesis (`synthesis/generate.py`) and the chat surface
(`chat/engine.py`), so a deployment can run without a hosted-API
dependency (Anthropic/Claude). This document is the deployment recipe;
`synthesis/llm_client.py`'s own docstring states the architectural rule
this respects: **no specific open-weight model is picked or hardcoded as
a default.** BioMistral-7B is documented here as *a* validated option a
deployer can choose, not the default `get_llm_client()` falls back to.

## Read this section first — the model publisher's own disclaimer

BioMistral's own model card ([huggingface.co/BioMistral/BioMistral-7B](https://huggingface.co/BioMistral/BioMistral-7B),
checked 2026-09-07) states directly:

> "We advise refraining from utilizing BioMistral in medical contexts
> unless it undergoes thorough alignment with specific use cases and
> undergoes further testing."

and separately advises against deploying it "for natural language
generation in production or for professional tasks in the realm of
health and medicine" without that further testing, describing it as
intended "strictly as a research tool."

This is not a formality to note in passing — it's the exact reason
issue #122 and issue #124 (citation-integrity structural eval, covering
every registered backend including this one) are sequenced together, and
the exact reason `synthesis/citation_gate.py`'s post-hoc check exists
independently of whatever a model is told in its system prompt. Nothing
in this document should be read as clearing BioMistral-7B for clinical
use — it clears it as *a backend the harness can now actually evaluate*,
which is a precondition for that judgment, not the judgment itself.

## What BioMistral-7B actually is

- **License:** Apache-2.0 (verified against the live model card,
  2026-09-07 — a fully permissive license with no clinical-use
  restriction *legally*; the restriction above is the publisher's own
  stated guidance, not a license term).
- **Base model:** Mistral-7B-Instruct-v0.1.
- **Training:** further pre-trained on PubMed Central Open Access
  articles (CC0/CC BY/CC BY-SA/CC BY-ND licensed text).
- **Publisher:** the BioMistral research team, trained on the CNRS Jean
  Zay French HPC cluster.
- **Parameters:** 7B — fp16 weights are ~14 GB on disk; a 4-bit
  quantized (AWQ/GPTQ) version is roughly 4–5 GB. Community GGUF
  quantizations also exist on Hugging Face for CPU-only serving via
  `llama.cpp`/Ollama, though this document does not name or verify a
  specific one — search Hugging Face for a current, actively maintained
  BioMistral-7B GGUF repo rather than relying on a name pinned here,
  since community quantization repos come and go.

## Why `OpenAICompatibleClient` needs no code changes

`synthesis/llm_client.py`'s `OpenAICompatibleClient` already speaks the
standard OpenAI chat-completions wire format — the exact format vLLM,
Ollama, and text-generation-inference all implement when serving *any*
model behind an OpenAI-compatible endpoint, BioMistral-7B included. There
is nothing BioMistral-specific about the request/response shape: a chat
message list in, a `choices[0].message.content` string out. See
`tests/synthesis/test_llm_client.py`'s
`TestOpenAICompatibleCompleteAgainstAVllmShapedServer` for a mocked
round-trip proving the client sends and parses that exact shape
correctly — the closest this offline test suite can get to confirming
"works unmodified" without a live model behind it (see "What this
document does not verify," below).

**A dedicated client subclass would only be needed if** BioMistral-7B's
recommended chat/instruction template diverges from what the serving
framework (vLLM/Ollama) already applies automatically via its chat
template config. As of this check, it does not — Mistral-7B-Instruct's
standard `[INST]...[/INST]` template is what BioMistral inherited and
what vLLM applies via its own chat-template resolution, no custom
template file required for a standard `vllm serve` invocation.

## Deployment recipe: vLLM (recommended, GPU)

vLLM is the recommended serving framework here because it's the most
widely used, best-documented OpenAI-compatible server for this class of
model, and its default CLI needs no extra flags to expose a working
`/v1/chat/completions` endpoint.

### Local (no Docker), for a quick check

```bash
pip install vllm
vllm serve BioMistral/BioMistral-7B
```

Confirmed against vLLM's own current documentation (2026-09-07): this
starts an OpenAI-compatible server on `http://localhost:8000`, exposing
`/v1/chat/completions` (also `/v1/completions`, `/v1/models`) — no
`--host`/`--port` flags needed for the default local case.

### Docker

```yaml
# Add alongside docker-compose.yml's existing services -- not merged
# into it here, since this is an optional, resource-heavy addition a
# deployer opts into, not a default part of the stack (matching
# ARCHITECTURE.md's "no open-weight model hardcoded" rule one level up,
# at the infrastructure layer).
services:
  biomistral:
    image: vllm/vllm-openai:latest
    # Image name per vLLM's own documented convention for its official
    # OpenAI-compatible server image (ROCm/XPU variants are published
    # under -rocm/-xpu suffixes for non-NVIDIA hardware) -- verify the
    # exact current tag against https://docs.vllm.ai before deploying,
    # since this was not independently pulled/run in this environment
    # (see "What this document does not verify").
    container_name: athena-biomistral
    command: ["--model", "BioMistral/BioMistral-7B"]
    ports:
      - "8001:8000"
    volumes:
      - biomistral_cache:/root/.cache/huggingface
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    restart: unless-stopped

volumes:
  biomistral_cache:
```

Then point Athena at it (`.env`):

```bash
ATHENA_LLM_ENABLED=true
ATHENA_LLM_PROVIDER=openai_compatible
ATHENA_LLM_BASE_URL=http://localhost:8001/v1
ATHENA_LLM_MODEL=BioMistral/BioMistral-7B
# ATHENA_LLM_API_KEY=   # unset -- vLLM's default config has no auth;
                         # see the "Securing this" note below before any
                         # non-loopback deployment
```

If running the `api` container from the main `docker-compose.yml` in the
*same* compose project as this service, use the service's Docker DNS
name instead of `localhost` for `ATHENA_LLM_BASE_URL`
(`http://biomistral:8000/v1`) — container-to-container traffic, unlike
the browser-facing `VITE_API_BASE`, does use Docker's internal network.

### Alternative: Ollama (CPU-friendly, quantized, easier local setup)

For a deployer without a GPU, or wanting a much smaller download:

```bash
ollama serve
ollama pull <a current BioMistral-7B GGUF tag on Ollama's library or
             Hugging Face, e.g. via `ollama pull hf.co/<org>/<repo>:<quant>` --
             verify the exact current tag yourself; not pinned here for
             the same reason the GGUF repo above isn't named>
```

Ollama also exposes an OpenAI-compatible endpoint at
`http://localhost:11434/v1` — set `ATHENA_LLM_BASE_URL` to that instead.
Expect materially slower generation and a noticeably degraded
quality/latency tradeoff versus full-precision GPU serving; this path is
documented as a genuine option for low-resource deployments (this
project's own stated low-resource-first design principle), not a
recommended default.

## Hardware sizing

**This section is estimates, not measurements, and says so explicitly**
— `docs/deployment/hardware-sizing.md`'s own standard for this repo is
real, measured figures (`docker stats` against a running container), and
this document does not meet that bar, for an honest reason: doing so
needs a GPU capable of running a 7B model, which was not available in
the environment this document was written in. Treat every number below
as a vendor-typical figure for a model of this size and quantization
level, not an Athena-specific measurement, until someone runs this for
real and replaces this section — the same way `hardware-sizing.md`
itself documents its own re-measurement history rather than treating a
first pass as final.

| Serving mode | Typical VRAM/RAM | Notes |
|---|---|---|
| vLLM, fp16 (full precision) | ~16 GB+ VRAM | Fits a single 24 GB consumer GPU (RTX 3090/4090, A10) comfortably; vLLM's own KV-cache overhead adds further VRAM beyond raw weight size, budget accordingly |
| vLLM/TGI, 4-bit (AWQ/GPTQ) quantized | ~6–8 GB VRAM | Fits smaller GPUs; expect a real, unmeasured-here quality tradeoff |
| Ollama/llama.cpp, CPU-only GGUF, 4-bit | ~6–8 GB system RAM | No GPU required; generation latency will be substantially slower than the GPU paths above |

## Running the LLM Decision-Quality & Safety Monitoring Harness against this backend

Point `.env` at the running BioMistral endpoint (as above), then:

```bash
# Breast cancer is issue #121's chosen MVP cancer type -- this is the
# vocabulary that actually matters for the MVP demo, per #122's own
# stated dependency on #121.
python validation/llm_eval_run.py --subsystem synthesis --cases breast_cancer

# Also run the existing general eval set for broader regression coverage,
# and the grounded-vs-ungrounded comparison (Ferber 2025's pattern,
# already used elsewhere in this harness) to check retrieval is actually
# changing this specific model's behavior, not just decorating it:
python validation/llm_eval_run.py --subsystem synthesis --cases both --grounded-comparison
```

Results land in `validation/llm_eval_results.md`, labeled by which eval
set produced them (`synthesis.generate` vs. `synthesis.generate
(breast_cancer eval set)`) so the report stays self-documenting about
what was actually evaluated — see `validation/llm_eval_run.py`'s
`_CASE_SETS` mapping.

**Do not treat a PASS here as clinical validation.** This harness checks
citation-grounding discipline (does the model cite what it was actually
given, does it avoid asserting a treatment recommendation) against a
small, hand-labeled held-out set — it is not, and does not claim to be,
a comprehensive clinical-accuracy evaluation. That distinction matters
doubly for this specific model given its publisher's own disclaimer
above.

## License

Recorded in `docs/deployment/license-audit.yaml` under a new `models:`
section (extending that file's existing `infrastructure:` precedent —
Docker-image / non-pip-installed assets that still ship as part of a
real deployment get an audited entry, the same transparency reasoning as
the `falkordb-server` entry already there). Apache-2.0, fully permissive,
no conflict with Athena's own AGPL-3.0 + commercial-license model.

## What this document does not verify

Stated plainly, per this project's own standing discipline
(`README.md`'s "before you demo this" warning, `ISSUES.md` throughout):

- **No live BioMistral-7B server was actually started or queried while
  writing this document or its accompanying tests.** There was no GPU
  (or a machine with enough free RAM for CPU inference at usable speed)
  available in the environment this work was done in. Every claim above
  about vLLM's CLI/server behavior was checked against vLLM's own current
  published documentation (2026-09-07), not observed directly.
- **The hardware-sizing table above is vendor-typical, not measured**, as
  stated in that section.
- **The harness has not actually been run against this backend.** The
  `--cases breast_cancer` flag and the breast-cancer eval set
  (`tests/harness/eval_sets/synthesis_breast_cancer.py`) are built,
  tested offline against a mocked client, and ready to run — but no one
  has run them against real BioMistral-7B output yet, so there is no
  real pass/fail verdict to report for this backend today.
- **The Ollama GGUF path names no specific quantization repo/tag**,
  deliberately — see that section for why.

Whoever has GPU access should be the one to close these gaps: start the
server per the recipe above, run the harness command above for real, and
replace this section (and the hardware-sizing table) with actual
results — the same way `hardware-sizing.md`'s own history shows a first
pass being corrected once someone could actually measure it.

## Securing this before any non-loopback deployment

vLLM's default configuration has **no authentication** on its API
server. `ATHENA_LLM_API_KEY` exists specifically to let
`OpenAICompatibleClient` send a bearer token, but vLLM does not check one
by default — running this behind anything other than `localhost`/an
internal trusted network without adding your own auth layer (a reverse
proxy with auth, vLLM's own `--api-key` flag if the installed version
supports it, or network-level isolation) would expose an unauthenticated
LLM endpoint. Verify the currently-installed vLLM version's own auth
options before any deployment reachable from outside a trusted network.
