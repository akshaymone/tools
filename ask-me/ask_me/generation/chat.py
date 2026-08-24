import logging
from typing import TypedDict, Annotated, Sequence, Dict, Any, List
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from ..api_client import FMGatewayClient
from ..retrieval.search import Retriever

logger = logging.getLogger(__name__)

class AgentState(TypedDict):
    messages: Sequence[BaseMessage]
    context: str
    retrieved_images: List[str]

class ChatAgent:
    def __init__(self):
        self.retriever = Retriever()
        self.api = FMGatewayClient()
        
        # Build LangGraph
        workflow = StateGraph(AgentState)
        workflow.add_node("retrieve", self.retrieve_node)
        workflow.add_node("generate", self.generate_node)
        workflow.add_node("fetch", self.fetch_node)
        
        workflow.add_edge(START, "retrieve")
        workflow.add_edge("retrieve", "generate")
        
        # Agentic Loop: Conditionally go to fetch if VLM requests a page, else END
        workflow.add_conditional_edges(
            "generate",
            self.should_fetch,
            {
                "fetch": "fetch",
                "end": END
            }
        )
        workflow.add_edge("fetch", "generate")
        
        self.app = workflow.compile()
        logger.info("LangGraph ChatAgent compiled and ready.")

    def retrieve_node(self, state: AgentState) -> dict:
        """Retrieves context from Qdrant based on the latest user message."""
        # To handle follow-up questions, we combine the last two user messages
        # into a single query so the retriever doesn't lose context on pronouns like "it" or "this".
        recent_user_texts = []
        for msg in reversed(state["messages"]):
            if isinstance(msg, HumanMessage):
                content = msg.content
                text = ""
                if isinstance(content, list):
                    for part in content:
                        if part.get("type") == "text":
                            text = part["text"]
                else:
                    text = str(content)
                recent_user_texts.insert(0, text)
            
            # Grab up to the last 2 human messages
            if len(recent_user_texts) >= 2:
                break
                
        search_query = " ".join(recent_user_texts)
        logger.info(f"Extracting context for search query: {search_query[:50]}...")
        results = self.retriever.search(query=search_query)
        
        # Format the context
        context_str = "--- RETRIEVED KNOWLEDGE ---\n"
        context_str += "The following are exact visual snapshots of the most relevant pages retrieved from the document corpus.\n"
        retrieved_images = []
        
        # Only use the top 3 results to match the VLM token limits in generate_node
        for i, res in enumerate(results[:3]):
            # Include the filename and page number to prevent hallucination
            doc_source = res.get("doc_name", "Unknown Document")
            page = res.get("page_number", "?")
            context_str += f"Image {i+1} --- Source: {doc_source} (Page {page}) ---\n"
            
            if res.get("base64"):
                retrieved_images.append(res["base64"])
            context_str += "\n"
            
        return {"context": context_str, "retrieved_images": retrieved_images}

    def generate_node(self, state: AgentState) -> dict:
        """Generates the final response using the VLM via FM Gateway."""
        system_prompt = (
            "You are a highly analytical senior technical assistant. "
            "I will provide you with retrieved visual snapshots of document pages. "
            "Do not just blindly repeat text. Analyze the charts, tables, and text in the provided context, "
            "synthesize the information, and provide a thoughtful, well-reasoned answer to the user's question.\n"
            "CRITICAL INSTRUCTION: You must fully extract and explain the information in your response. "
            "NEVER tell the user to 'look at page X' or 'refer to the flowchart/image'. "
            "The user cannot see the images you see. You must transcribe and explain the steps, data, or details directly.\n\n"
            "--- TOOL: FETCH_PAGE (CRITICAL) ---\n"
            "If the provided pages (e.g., a Table of Contents) indicate that the answer is on a specific page that was NOT provided, "
            "you MUST fetch that page yourself using the tool below. NEVER ask the user to provide the missing page.\n"
            "To use the tool, output EXACTLY the following on a new line and nothing else:\n"
            "<FETCH_PAGE doc=\"document_name.pdf\" page=\"X\" />\n"
            "Replace 'document_name.pdf' with the exact Source name from the context and 'X' with the integer page number. "
            "Wait for the system to provide the page in the next turn.\n"
            "------------------------\n\n"
            f"{state['context']}"
        )
        
        api_messages = [{"role": "system", "content": system_prompt}]
        
        for idx, msg in enumerate(state["messages"]):
            role = "user" if isinstance(msg, HumanMessage) else "assistant"
            content = msg.content
            
            # If this is the LAST user message, attach retrieved images so the VLM can literally see them
            if role == "user" and idx == len(state["messages"]) - 1 and state.get("retrieved_images"):
                if isinstance(content, str):
                    content = [{"type": "text", "text": content}]
                elif isinstance(content, list):
                    content = list(content) # shallow copy
                
                # Add a strong reminder at the end of the user's message
                content.append({
                    "type": "text", 
                    "text": "\n\n[SYSTEM REMINDER: If the visual context indicates the answer is on a page you don't have, DO NOT ask me for it or tell me to read it. You MUST use the tool by outputting EXACTLY: <FETCH_PAGE doc=\"document_name\" page=\"X\" />]"
                })
                
                # Append all retrieved images (retrieve_node limits to 3, fetch_node may add 1)
                for i, b64 in enumerate(state["retrieved_images"]):
                    logger.info("Injecting a retrieved image directly into VLM prompt.")
                    content.append({"type": "text", "text": f"Image {i+1}:"})
                    content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
            
            api_messages.append({"role": role, "content": content})
            
        logger.info("Calling VLM for final generation...")
        logger.debug(f"API Messages Payload: {api_messages}")
        response_text = self.api.chat_completion(messages=api_messages)
        
        # Append the new AIMessage to the existing list
        new_messages = list(state["messages"])
        new_messages.append(AIMessage(content=response_text))
        return {"messages": new_messages}

    def should_fetch(self, state: AgentState) -> str:
        last_message = state["messages"][-1]
        if isinstance(last_message, AIMessage) and "FETCH_PAGE" in last_message.content:
            return "fetch"
        return "end"

    def fetch_node(self, state: AgentState) -> dict:
        import re
        last_message = state["messages"][-1]
        content = last_message.content
        
        logger.info("Agent triggered FETCH_PAGE tool.")
        # Lenient regex: allows optional < />, single/double quotes, or no quotes for page
        match = re.search(r'FETCH_PAGE\s+doc=["\']?([^"\'>]+)["\']?\s+page=["\']?(\d+)["\']?', content)
        if not match:
            logger.warning("Failed to parse FETCH_PAGE tool call.")
            new_msg = HumanMessage(content="Error: Could not parse TOOL call. Please use the exact format: <FETCH_PAGE doc=\"...\" page=\"...\" />")
            return {"messages": list(state["messages"]) + [new_msg]}
            
        doc_name = match.group(1)
        try:
            page = int(match.group(2))
        except ValueError:
            new_msg = HumanMessage(content="Error: page must be an integer.")
            return {"messages": list(state["messages"]) + [new_msg]}
            
        page_data = self.retriever.fetch_page(doc_name, page)
        
        if not page_data or not page_data.get("base64"):
            new_msg = HumanMessage(content=f"Error: Could not find page {page} for document {doc_name} in the index.")
            return {"messages": list(state["messages"]) + [new_msg]}
            
        new_b64 = page_data["base64"]
        new_img_index = len(state["retrieved_images"]) + 1
        
        new_context = state["context"] + f"Image {new_img_index} --- Source: {doc_name} (Page {page}) [FETCHED BY TOOL] ---\n\n"
        new_retrieved_images = list(state["retrieved_images"]) + [new_b64]
        
        new_msg = HumanMessage(content=f"Tool Success: I have fetched page {page} of {doc_name}. It is provided as Image {new_img_index} in your visual context. Please extract the specific technical steps.")
        
        return {
            "messages": list(state["messages"]) + [new_msg],
            "context": new_context,
            "retrieved_images": new_retrieved_images
        }

    def chat(self, user_input: str, image_base64: str = None, chat_history: List[BaseMessage] = None):
        """Helper to invoke the graph with an optional chat history."""
        if chat_history is None:
            chat_history = []
            
        content = []
        if user_input:
            content.append({"type": "text", "text": user_input})
        if image_base64:
            content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}})
            
        msg = HumanMessage(content=content if image_base64 else user_input)
        chat_history.append(msg)
        
        logger.info("Invoking LangGraph workflow...")
        result = self.app.invoke({"messages": chat_history, "context": ""})
        
        # Replace chat_history with the full message trace (including tool calls/responses)
        chat_history = list(result["messages"])
        return chat_history[-1].content, chat_history
