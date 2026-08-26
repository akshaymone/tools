# Features to be Built (Using Qwen3.6-27B)

While the Qwen3.6-27B model (with its massive 256K context window) cannot replace the current Gemma-4-31B-it Vision-Language Model due to its lack of direct image input capabilities, it can be utilized to build the following features and improvements:

## 1. Map-Reduce for Multi-Page Analysis
Currently, the pipeline limits visual context to the top 3 images to save tokens. For queries requiring analysis across many pages (e.g., summarizing 50 financial charts):
- Gemma can evaluate each page individually to extract text descriptions.
- Qwen can use its 256K context to read all the extracted text summaries and synthesize them into a single comprehensive report.

## 2. Query Decomposition & Agentic Routing
Place Qwen at the start of the LangGraph as a Router/Planner Node. For complex, multi-part questions:
- Qwen decomposes the question into separate targeted search queries.
- The pipeline fetches the relevant images for each sub-query.
- Gemma analyzes the specific images for each sub-query.

## 3. VLM Evaluator & Self-Correction
Use Qwen as an evaluator to check Gemma's output. After Gemma generates an answer based on images:
- Qwen reviews the user's question and Gemma's text answer.
- Qwen checks for logic gaps, formatting, and constraint adherence, refining the final response to improve accuracy.

## 4. Infinite Chat History
Leverage Qwen's 256K context limit to maintain extremely long chat histories. This allows users to refer back to any point in multi-hour diagnostic sessions without the system needing to summarize or drop older messages.

## 5. Agentic Web Search Tool for Missing Terminology
If a user asks for the definition of a technical term that is missing from the local documents, add an agentic loop tool (`<WEB_SEARCH query="..." />`). If the LLM cannot find the term locally, it can trigger a search (e.g., via Wikipedia/DuckDuckGo), inject the web summary into the context, and answer the user accurately.

## 6. Dedicated Local Glossary/Dictionary Index
For completely offline pipelines, allow the user to provide a `glossary.json` or dictionary file during ingestion. Create a secondary Qdrant collection just for terminology. The retriever would check this collection first before falling back to the heavy document image search.
