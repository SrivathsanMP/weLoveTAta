# Local model

Place the official Qwen2.5-0.5B-Instruct GGUF quantized as Q4_K_M at:

`models/qwen2.5-0.5b-instruct-q4_k_m.gguf`

The engine image builds `llama-cpp-python` for the target platform. Start with `MOCK_LLM=1`; deterministic intent routing and analytics work without a model. Set `MOCK_LLM=0` to load the local file. No model is downloaded by the application.