"""Generate a PNG diagram of the LangGraph agent architecture."""

from backend.graph import graph_builder

graph = graph_builder.compile()
graph.get_graph().draw_mermaid_png(
    output_file_path="graph_diagram.png",
    max_retries=5,
    retry_delay=2.0,
)
print("Saved graph_diagram.png")
