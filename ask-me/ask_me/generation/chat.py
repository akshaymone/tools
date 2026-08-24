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
        
        workflow.add_edge(START, "retrieve")
        workflow.add_edge("retrieve", "generate")
        workflow.add_edge("generate", END)
        
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
        for i, res in enumerate(results):
            # Include the filename and page number to prevent hallucination
            doc_source = res.get("doc_name", "Unknown Document")
            page = res.get("page_number", "?")
            context_str += f"--- Source: {doc_source} (Page {page}) ---\n"
            
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
            "synthesize the information, and provide a thoughtful, well-reasoned answer to the user's question.\n\n"
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
                
                # Append up to 3 retrieved images to prevent token limits
                for b64 in state["retrieved_images"][:3]:
                    logger.info("Injecting a retrieved image directly into VLM prompt.")
                    content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
            
            api_messages.append({"role": role, "content": content})
            
        logger.info("Calling VLM for final generation...")
        logger.debug(f"API Messages Payload: {api_messages}")
        response_text = self.api.chat_completion(messages=api_messages)
        
        return {"messages": [AIMessage(content=response_text)]}

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
        
        chat_history.append(result["messages"][-1])
        return result["messages"][-1].content, chat_history
