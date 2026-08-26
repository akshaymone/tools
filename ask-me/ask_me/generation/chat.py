import logging
import re
import concurrent.futures
from typing import TypedDict, Annotated, Sequence, Dict, Any, List
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from ..api_client import FMGatewayClient
from ..retrieval.search import Retriever
from ..config import settings

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
        
        # Allow up to 15 results for the new Map-Reduce pipeline
        for i, res in enumerate(results[:15]):
            # Include the filename and page number to prevent hallucination
            doc_source = res.get("doc_name", "Unknown Document")
            page = res.get("page_number", "?")
            context_str += f"Image {i+1} --- Source: {doc_source} (Page {page}) ---\n"
            
            if res.get("base64"):
                retrieved_images.append(res["base64"])
            context_str += "\n"
            
        return {"context": context_str, "retrieved_images": retrieved_images}

    def _generate_map_reduce(self, state: AgentState) -> dict:
        """Map-Reduce flow for large contexts (e.g. > 3 images)."""
        images = state["retrieved_images"]
        context_str = state["context"]
        
        # Find the last user message to understand the core question
        user_query = ""
        for msg in reversed(state["messages"]):
            if isinstance(msg, HumanMessage):
                if isinstance(msg.content, list):
                    for part in msg.content:
                        if part.get("type") == "text":
                            user_query = part["text"]
                else:
                    user_query = str(msg.content)
                break

        # Map step: Extract info from each image in parallel using Gemma
        logger.info(f"Map step: Extracting information from {len(images)} images in parallel.")
        map_prompt = (
            "You are an analytical assistant. I am providing you with a single document page as an image.\n"
            f"The user's query is: '{user_query}'\n"
            "Extract any charts, tables, facts, or text from this image that are relevant to the user's query. "
            "If the image does not contain relevant information, reply with 'No relevant information on this page.'\n"
            "Be highly detailed."
        )
        
        def process_image(idx, b64_img):
            messages = [
                {"role": "system", "content": map_prompt},
                {"role": "user", "content": [
                    {"type": "text", "text": f"Please analyze this image for relevant information."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}
                ]}
            ]
            try:
                # Map step uses VLM (Gemma)
                result = self.api.chat_completion(messages=messages, max_tokens=1000)
                return f"--- Summary of Image {idx+1} ---\n{result}\n"
            except Exception as e:
                logger.error(f"Error processing image {idx+1}: {e}")
                return f"--- Summary of Image {idx+1} ---\n[Error extracting data]\n"

        extracted_texts = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_idx = {executor.submit(process_image, i, img): i for i, img in enumerate(images)}
            for future in concurrent.futures.as_completed(future_to_idx):
                extracted_texts.append(future.result())

        combined_extractions = "\n".join(extracted_texts)
        
        # Reduce step: Synthesize with Qwen
        logger.info("Reduce step: Synthesizing Map extractions using Qwen.")
        reduce_system_prompt = (
            "You are a highly analytical senior technical assistant. "
            "I have already extracted the text and data from all relevant document pages using a Vision model. "
            "The extracted data is provided below. Synthesize this information and provide a thoughtful, well-reasoned answer to the user's question.\n"
            "CRITICAL INSTRUCTION: You must fully explain the information. Do not tell the user to look at the images, because you only have text extractions.\n"
            "GENERAL KNOWLEDGE FALLBACK: If the user asks for the definition or explanation of a technical term, and the provided document data does NOT contain the answer, you may use your internal pre-trained knowledge to define it. However, you MUST explicitly prepend that specific part of your answer with '[General Knowledge]' to warn the user that it was not found in the retrieved documents.\n\n"
            f"--- EXTRACTED PAGE DATA ---\n{combined_extractions}"
        )
        
        api_messages = [{"role": "system", "content": reduce_system_prompt}]
        for msg in state["messages"]:
            role = "user" if isinstance(msg, HumanMessage) else "assistant"
            content = msg.content
            if isinstance(content, list):
                # Flatten text for the text-only Qwen model
                text_parts = [part["text"] for part in content if part.get("type") == "text"]
                content = " ".join(text_parts)
            api_messages.append({"role": role, "content": str(content)})
            
        # Use Qwen for Synthesis
        response_text = self.api.chat_completion(
            messages=api_messages, 
            max_tokens=2000, 
            model=settings.synthesis_model
        )
        
        new_messages = list(state["messages"])
        new_messages.append(AIMessage(content=response_text))
        return {"messages": new_messages}

    def generate_node(self, state: AgentState) -> dict:
        """Generates the final response using the VLM via FM Gateway."""
        
        # Determine if we should use Map-Reduce (if more than 3 images are retrieved)
        if len(state.get("retrieved_images", [])) > 3:
            logger.info("More than 3 images retrieved. Triggering Map-Reduce pipeline.")
            return self._generate_map_reduce(state)
            
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
