class _LazyLLM:
    """Create the local LLM client only when an LLM call is actually requested."""

    def __init__(self):
        self._client = None

    def _load(self):
        if self._client is None:
            from langchain_openai import ChatOpenAI

            self._client = ChatOpenAI(
                model="Qwen/Qwen3.5-122B-A10B",
                base_url="http://127.0.0.1:5000/v1",
                api_key="local-proxy",
                temperature=0,
                timeout=120,
                max_retries=0,
            )
        return self._client

    def __getattr__(self, name):
        return getattr(self._load(), name)


llm = _LazyLLM()
