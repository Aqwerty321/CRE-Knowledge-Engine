# Runtime Notes

This repo normally works best in retrieval mode:

```bash
/home/Aaditya/bin/ai-profile retrieval
```

That keeps these services hot:

- `rag-embed.service`
- `rag-rerank.service`
- `local-reasoner.service`
- `neo4j-memory-mcp.service`

- `rag-embed.service` now serves `qwen3-embedding-0_6b-q8_0` on `http://127.0.0.1:8001/v1/embeddings`.
- `rag-rerank.service` now serves `qwen3-reranker-0.6b` on `http://127.0.0.1:8002/rerank`.

`local-reasoner.service` is a vLLM-backed NVFP4 model and has a noticeable cold-start path. The first startup can spend several minutes downloading weights, compiling, and warming the model before `http://127.0.0.1:8000/v1/models` responds. Treat the service as healthy only after the OpenAI-compatible endpoint answers requests, not just after systemd shows it as running.

Firecrawl reads its LLM-assisted extraction settings from `/home/Aaditya/services/firecrawl/.env` when the `api` container is created. This affects schema extraction, prompt-driven extraction, and other agentic research paths that rely on the configured model. After changing `OPENAI_API_KEY`, `OPENAI_BASE_URL`, or `MODEL_NAME`, recreate the `api` container so the new env is applied:

```bash
/home/Aaditya/bin/firecrawl-compose up -d --force-recreate api
```

This is enough for Firecrawl model changes. The rest of the Firecrawl stack does not need to be restarted unless other services changed.

Gemma mode is:

```bash
/home/Aaditya/bin/ai-profile gemma
```

The Gemma service start script currently targets `/home/Aaditya/models/RedHatAI-gemma-4-26B-A4B-it-NVFP4`.

The current stable local Gemma path uses `VLLM_NVFP4_GEMM_BACKEND=cutlass` and does not force a `--moe-backend` override. On this machine, that path successfully serves `gemma4-26b-a4b-nvfp4` at `http://127.0.0.1:8000/v1/models`.

`LilaRest/gemma-4-31B-it-NVFP4-turbo` was evaluated on this machine with `vllm-nightly` on CUDA 13.0 and Blackwell-class FP4 support. `vllm` recognized the model and `modelopt` quantization correctly, but the service failed to initialize reliably because the local `RTX 5090 Laptop GPU` only exposes about 24 GB VRAM and did not have enough startup headroom for the 31B turbo checkpoint in the normal desktop environment. Treat the model card's RTX 5090 fit claim as guidance for desktop 32 GB 5090-class setups, not as a guaranteed fit for this laptop GPU.

`graphify-local` only knows what is in `graphify-out/graph.json`. Rebuild the graph artifacts if major repo structure changes make Graphify answers look stale.

The local Graphify runtime is pinned operationally to `graphifyy 0.4.12`. That line has the practical balance of MCP stability and Python compatibility on this machine, and the local wrapper layer carries the remaining repo-specific cleanup and bootstrap behavior.
