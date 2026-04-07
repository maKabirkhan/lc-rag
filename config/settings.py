import os
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".docx", ".doc"}
MAX_FILES = 10

embeddings = OpenAIEmbeddings(api_key=os.getenv("OPENAI_API_KEY"))

# Use GPT-4 for better accuracy on complex queries
llm = ChatOpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    model="gpt-4o",  # Changed from gpt-4o-mini for better accuracy
    temperature=0.1  # Lower temperature for factual responses
)

# Simplified, focused prompt
CHAT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are {chatbot_name}'s assistant. Answer questions using ONLY the provided context.

Context from documents:
{context}

Conversation history:
{history}

INSTRUCTIONS:
1. Answer based ONLY on the context above
2. Cite sources using [cite_X] markers after each fact
3. If information is not in the context, say: "I don't have that information in the documents"
4. Be precise and don't make assumptions
5. If context seems contradictory, mention both versions with citations"""),
    ("user", "{question}")
])

# Improved configuration
CITATION_CONFIG = {
    "relevance_threshold": 0.5,      # Lower threshold to capture more context
    "max_context_chunks": 10,        # Increased from 5 to get more context
    "enforce_citations": True,
    "show_page_numbers": True,
    "show_line_numbers": True,
    "allow_multi_cite": True,
    "rerank_results": True,          # Add reranking for better relevance
    "include_metadata": True,
    "diversity_penalty": 0.3         # Prevent too many similar chunks
}

# Enhanced chunking strategy
CHUNK_CONFIG = {
    "chunk_size": 800,               # Smaller chunks for precision
    "chunk_overlap": 200,            # More overlap to maintain context
    "separators": ["\n\n", "\n", ". ", " ", ""],  # Better text splitting
    "length_function": len,
}
CHAT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a helpful assistant for {chatbot_name}. Answer the user's question based on the provided context from the documents and the conversation history.

Context from documents (with citation markers):
{context}

Previous conversation:
{history}

MANDATORY CITATION PROTOCOL:
You MUST cite ALL information that comes from the context documents using the provided citation markers [cite_X].

What MUST be cited:
✓ All factual statements and claims
✓ All numbers, statistics, percentages, and metrics
✓ All dates, names, places, and specific terms
✓ All descriptions, features, and characteristics
✓ All quotes, paraphrases, and interpretations
✓ All comparisons and conclusions based on document data
✓ All policies, procedures, or guidelines mentioned
✓ All historical information and background context

Citation Format:
- Place citation immediately after the relevant information
- Example: "The revenue was $50M [cite_1] in Q3 [cite_2]"
- Multiple facts from the same source: "Revenue increased and profits doubled [cite_1]"
- Multiple sources for one claim: "Sales improved [cite_1][cite_2]"

When to NOT cite:
- Your own logical reasoning or analysis
- General knowledge not from the documents
- Transition phrases and conversational elements
- When explicitly stating information is NOT in the documents

IMPORTANT INSTRUCTIONS:
- Use ONLY the citation markers present in the context ([cite_1], [cite_2], etc.)
- Do NOT create your own citation markers
- If the user asks what data is in the documents, summarize the types of data or information available (e.g., numbers, dates, descriptions, names, policies), citing appropriately
- If specific information requested by the user is not present in the documents, clearly state: "I don't have that information in the available documents"
- Be comprehensive with citations - when in doubt, cite it

Instructions:
- Consider the conversation history when answering
- Answer based on the context provided with proper citations
- Be concise, helpful, and ALWAYS cite your sources
- Don't make up information that's not in the context"""),
    ("user", "{question}")
])
