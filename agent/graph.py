from langgraph.graph import StateGraph, END
from agent.state import GraphState
from agent.nodes.router import router_node
from agent.nodes.retrieve import retrieve_node
from agent.nodes.synthesize import synthesize_node
from agent.nodes.translate import translate_node

def build_graph():
    g = StateGraph(GraphState)
    g.add_node("router", router_node)
    g.add_node("retrieve", retrieve_node)
    g.add_node("synthesize", synthesize_node)
    g.add_node("translate", translate_node)
    g.set_entry_point("router")
    g.add_edge("router", "retrieve")
    g.add_edge("retrieve", "synthesize")
    g.add_edge("synthesize", "translate")
    g.add_edge("translate", END)
    return g.compile()

graph = build_graph()

def run_query(query: str, target_language: str = "en") -> dict:
    init: GraphState = {
        "query": query,
        "query_type": "standard_lookup",  # placeholder overwritten by router
        "retrieved_docs": [],
        "used_live_fallback": False,
        "answer": "",
        "citations": [],
        "target_language": target_language,  # type: ignore
        "translated_answer": None,
    }
    result = graph.invoke(init)
    return result

if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "What is IS 2347 and which products does it cover?"
    import json
    out = run_query(q)
    print(json.dumps({k: out.get(k) for k in ["query","query_type","used_live_fallback","answer","citations"]}, indent=2, ensure_ascii=False))
