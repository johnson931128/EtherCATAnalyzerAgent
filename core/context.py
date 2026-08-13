from core.config import AGENTS_PATH
from core.state import AgentState


def load_context(state: AgentState):
    context = AGENTS_PATH.read_text(encoding="utf-8")
    return {"context": context}
