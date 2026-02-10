"""
QUICK TEST SCRIPT
=================
Runs automated tests to verify the agent is working correctly.

Usage:
    python 03_test.py
"""

import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.utilities import SQLDatabase
from langchain_postgres.vectorstores import PGVector
from langchain.agents import Tool, AgentExecutor, create_openai_functions_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

load_dotenv()

READONLY_DB_URL = os.getenv("READONLY_DATABASE_URL")
DATABASE_URL = os.getenv("DATABASE_URL")

# Setup (same as 02_agent.py but condensed)
sql_db = SQLDatabase.from_uri(READONLY_DB_URL, sample_rows_in_table_info=2)
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
vectorstore = PGVector(connection=DATABASE_URL, collection_name="text_embeddings", embeddings=embeddings)

def sql_tool(query: str) -> str:
    try:
        if not query.upper().strip().startswith("SELECT"):
            return "Error: Only SELECT allowed"
        return sql_db.run(query) or "No results"
    except Exception as e:
        return f"Error: {e}"

def semantic_tool(query: str) -> str:
    try:
        docs = vectorstore.similarity_search(query, k=3)
        if not docs:
            return "No results"
        return "\n\n".join([
            f"{i+1}. {d.metadata.get('name', 'N/A')}\n   {d.page_content[:150]}..."
            for i, d in enumerate(docs)
        ])
    except Exception as e:
        return f"Error: {e}"

tools = [
    Tool(name="SQLDatabase", func=sql_tool, description="SQL queries for structured data"),
    Tool(name="SemanticSearch", func=semantic_tool, description="Semantic search by meaning"),
]

llm = ChatOpenAI(model="gpt-4", temperature=0)
prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a database assistant. Use SQLDatabase for counts/filters, SemanticSearch for descriptions."),
    ("human", "{input}"),
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])

agent = create_openai_functions_agent(llm, tools, prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

# Run tests
print("=" * 70)
print("AUTOMATED TESTS")
print("=" * 70)

tests = [
    "How many products are in the database?",
    "What's the total revenue from all orders?",
    "Find products good for gaming",
    "Show me reviews mentioning battery",
]

for i, question in enumerate(tests, 1):
    print(f"\n🧪 TEST {i}/{len(tests)}: {question}")
    print("-" * 70)
    try:
        result = agent_executor.invoke({"input": question})
        print(f"\n✅ Answer: {result['output']}\n")
    except Exception as e:
        print(f"\n❌ Error: {e}\n")

print("=" * 70)
print("✅ TESTING COMPLETE")
print("=" * 70)