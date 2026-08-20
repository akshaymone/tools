import logging
from typing import TypedDict, Annotated, Sequence, Dict, Any
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from ..api_client import FMGatewayClient
from ..retrieval.search import Retriever

logger = logging.getLogger(__name__)

class AgentState(TypedDict):
    messages: Sequence[BaseMessage]
    context: str

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
        latest_msg = state["messages"][-1].content
        
        # Check if the message contains an image (multimodal query)
        query_text = ""
        query_image = None
        
        if isinstance(latest_msg, list):
            for part in latest_msg:
                if part.get("type") == "text":
                    query_text = part["text"]
                elif part.get("type") == "image_url":
                    # Remove the data URI prefix for the retriever
                    query_image = part["image_url"]["url"].split(",", 1)[-1]
        else:
            query_text = str(latest_msg)
            
        logger.info(f"Extracting context for user message: {query_text[:50]}...")
        results = self.retriever.search(query=query_text, query_image_base64=query_image)
        
        # Format the context
        context_str = "--- RETRIEVED KNOWLEDGE ---\n"
        for i, res in enumerate(results):
            context_str += f"Section {i+1}:\n{res['text']}\n"
            for vis in res["visuals"]:
                if vis.get("flowchart_description"):
                    context_str += f"[Flowchart Context]: {vis['flowchart_description']}\n"
            context_str += "\n"
            
        return {"context": context_str}

    def generate_node(self, state: AgentState) -> dict:
        """Generates the final response using the VLM via FM Gateway."""
        system_prompt = SystemMessage(
            content=f"You are a helpful technical assistant. Use the following retrieved context to answer the user's question accurately.\n\n{state['context']}"
        )
        
        # Convert LangChain messages to the dictionary format expected by FM Gateway
        api_messages = []
        for msg in [system_prompt] + list(state["messages"]):
            role = "user" if isinstance(msg, HumanMessage) else "assistant"
            if isinstance(msg, SystemMessage):
                role = "system"
            api_messages.append({"role": role, "content": msg.content})
            
        logger.info("Calling VLM for final generation...")
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
