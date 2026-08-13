from core.state import AgentState
from retrieval.source_retrieval import select_source_with_llm


def select_source(state: AgentState):
    selection = select_source_with_llm(state["task"], max_files=3)
    selected_paths = selection["selected_paths"]
    source_texts = selection["source_texts"]

    source_code = "\n\n".join(
        f"===== Source: {path} =====\n\n{source_texts[path]}"
        for path in selected_paths
    )

    return {
        "selected_source": "\n".join(selected_paths),
        "source_code": source_code,
    }
