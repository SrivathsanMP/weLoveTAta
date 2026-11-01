"""Optional local-only llama.cpp intent classifier; never generates factual answers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def load_model() -> Any | None:
    if os.environ.get("MOCK_LLM", "1") == "1":
        return None
    model_path = Path(os.environ.get("MODEL_PATH", "/models/qwen2.5-0.5b-instruct-q4_k_m.gguf"))
    if not model_path.is_file():
        print(f"Model not found at {model_path}; using deterministic intent fallback", flush=True)
        return None
    from llama_cpp import Llama, LlamaGrammar

    grammar_path = Path(__file__).with_name("grammar.gbnf")
    model = Llama(model_path=str(model_path), n_ctx=1024, n_threads=2, verbose=False)
    model.grammar = LlamaGrammar.from_file(str(grammar_path))
    return model