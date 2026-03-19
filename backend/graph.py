"""
LangGraph state graph: nodes, routing functions, and graph assembly.
"""

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from backend.prompts import request_analyser_prompt, response_formatter_prompt
from backend.tools import api_call_tool, ready_to_format, semantic_search_tool

# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------
llm = init_chat_model("gpt-4o", model_provider="openai", temperature=0)

# ---------------------------------------------------------------------------
# Chains (prompt | LLM, composed once at module level)
# ---------------------------------------------------------------------------
analyser_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", request_analyser_prompt),
        MessagesPlaceholder(variable_name="messages"),
    ]
)
analyser_chain = analyser_prompt | llm.bind_tools(
    [api_call_tool, semantic_search_tool, ready_to_format]
)

formatter_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", response_formatter_prompt),
        MessagesPlaceholder(variable_name="messages"),
    ]
)
formatter_chain = formatter_prompt | llm


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------
def request_analyser(state: MessagesState):
    response = analyser_chain.invoke({"messages": state["messages"]})
    return {"messages": [response]}


tool_node = ToolNode(tools=[api_call_tool, semantic_search_tool, ready_to_format])


def make_api_response_readable(state: MessagesState):
    user_question = None
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            user_question = msg
            break

    tool_content = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, ToolMessage) and msg.name == "APIInput":
            tool_content = msg.content
            break

    subset = []
    if user_question:
        subset.append(user_question)
    subset.append(HumanMessage(content=f"Raw API response:\n{tool_content}"))

    response = formatter_chain.invoke({"messages": subset})
    return {"messages": [response]}


# ---------------------------------------------------------------------------
# Node names
# ---------------------------------------------------------------------------
NODE_REQUEST_ANALYSER = "request_analyser"
NODE_TOOL_CALL = "tool_call"
NODE_FORMAT_RESPONSE = "make_api_response_readable"


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------
def route_after_analyser(state: MessagesState) -> str:
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return NODE_TOOL_CALL
    return END


def route_after_tools(state: MessagesState) -> str:
    for msg in reversed(state["messages"]):
        if isinstance(msg, ToolMessage):
            if msg.name == "ready_to_format":
                return NODE_FORMAT_RESPONSE
            return NODE_REQUEST_ANALYSER
    return END


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------
graph_builder = StateGraph(MessagesState)

graph_builder.add_node(NODE_REQUEST_ANALYSER, request_analyser)
graph_builder.add_node(NODE_TOOL_CALL, tool_node)
graph_builder.add_node(NODE_FORMAT_RESPONSE, make_api_response_readable)

graph_builder.add_edge(START, NODE_REQUEST_ANALYSER)
graph_builder.add_conditional_edges(
    NODE_REQUEST_ANALYSER,
    route_after_analyser,
    {NODE_TOOL_CALL: NODE_TOOL_CALL, END: END},
)
graph_builder.add_conditional_edges(
    NODE_TOOL_CALL,
    route_after_tools,
    {
        NODE_REQUEST_ANALYSER: NODE_REQUEST_ANALYSER,
        NODE_FORMAT_RESPONSE: NODE_FORMAT_RESPONSE,
        END: END,
    },
)
graph_builder.add_edge(NODE_FORMAT_RESPONSE, END)
