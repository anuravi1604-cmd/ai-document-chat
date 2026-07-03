import os
import json
import pickle
import requests
import numpy as np
import faiss
from typing import List, Dict, Tuple, Any
from docx import Document as DocxDoc
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer, CrossEncoder
from rank_bm25 import BM25Okapi
import ollama
import networkx as nx

from backend.app.config import (
    EMBEDDING_MODEL_NAME,
    RERANKER_MODEL_NAME,
    INDEX_DIR,
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL_NAME,
    OLLAMA_MODEL_NAME,
    OLLAMA_API_URL,
    DATA_DIR
)

import chromadb
chroma_client = chromadb.PersistentClient(path=os.path.join(DATA_DIR, "chroma_db"))
chroma_collection = chroma_client.get_or_create_collection(name="contextiq_docs")

# Global models cached inside memory to avoid loading on every query
_embedding_model = None
_reranker_model = None
_openrouter_rate_limited = False

def get_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        print(f"Loading embedding model: {EMBEDDING_MODEL_NAME}...")
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME, device="cpu")
        print("Embedding model loaded successfully.")
    return _embedding_model

def get_reranker_model() -> CrossEncoder:
    global _reranker_model
    if _reranker_model is None:
        print(f"Loading reranker model: {RERANKER_MODEL_NAME}...")
        _reranker_model = CrossEncoder(RERANKER_MODEL_NAME, device="cpu")
        print("Reranker model loaded successfully.")
    return _reranker_model


# --- DOCUMENT PARSERS ---

def is_garbage_text(text: str) -> bool:
    """Detects if extracted text consists of corrupted or garbage font characters."""
    if not text:
        return True
    stripped = text.strip()
    if not stripped:
        return True
    # Count alphanumeric characters, standard spaces, and basic punctuation
    normal_chars = sum(1 for c in stripped if c.isalnum() or c.isspace() or c in ".,?!'\"()-:;@_")
    ratio = normal_chars / len(stripped)
    return ratio < 0.70  # Less than 70% standard characters points to garbled fonts

def parse_document(file_path: str) -> str:
    """Detects extension and parses PDF, DOCX, TXT or MD files into markdown representation."""
    ext = os.path.splitext(file_path)[1].lower()
    
    if ext == ".pdf":
        print(f"[Parser] Parsing PDF with Tesseract OCR: {file_path}")
        try:
            from pdf2image import convert_from_path
            import pytesseract
            
            images = convert_from_path(file_path)
            text_blocks = []
            
            for i, img in enumerate(images):
                page_text = pytesseract.image_to_string(img)
                text_blocks.append(f"--- PAGE {i+1} ---\n{page_text}")
                
            return "\n\n".join(text_blocks)
        except Exception as e:
            raise RuntimeError(f"Failed to parse PDF with Tesseract: {str(e)}")
        
    elif ext == ".docx":
        print(f"Parsing DOCX with python-docx: {file_path}")
        doc = DocxDoc(file_path)
        text_blocks = []
        
        # Parse paragraphs
        for para in doc.paragraphs:
            if para.text.strip():
                text_blocks.append(para.text.strip())
                
        # Parse tables
        for table in doc.tables:
            text_blocks.append("\nTABLE:")
            for row in table.rows:
                row_cells = [cell.text.strip() for cell in row.cells]
                text_blocks.append(" | ".join(row_cells))
            text_blocks.append("") # space below table
            
        return "\n".join(text_blocks)
        
    elif ext in [".txt", ".md", ".markdown"]:
        print(f"Reading text-based file: {file_path}")
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
            
    else:
        raise ValueError(f"Unsupported file extension '{ext}'. Must be PDF, DOCX, TXT or MD.")


# --- SMART CHUNKER ---

class SmartChunker:
    """Chunknize helper that splits documents using markdown headers and recursive constraints."""
    
    def __init__(self, chunk_size: int = 1200, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        
    def split_text(self, text: str) -> List[Dict[str, Any]]:
        """Splits markdown text structure-aware, protecting tables and formatting headers."""
        # 1. Header-based split
        headers_to_split_on = [
            ("#", "Header 1"),
            ("##", "Header 2"),
            ("###", "Header 3"),
        ]
        
        markdown_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=headers_to_split_on
        )
        md_splits = markdown_splitter.split_text(text)
        
        # 2. Secondary recursive split
        recursive_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap
        )
        
        chunks = []
        for idx, doc in enumerate(md_splits):
            content = doc.page_content
            metadata = doc.metadata
            
            sub_splits = recursive_splitter.split_text(content)
            for sub_idx, sub_content in enumerate(sub_splits):
                # Is it a table?
                is_table = False
                lines = sub_content.strip().split("\n")
                if len(lines) >= 2:
                    is_table = "|" in lines[0] and "|" in lines[1] and "---" in lines[1]
                
                chunks.append({
                    "content": sub_content,
                    "metadata": {
                        **metadata,
                        "sub_index": sub_idx,
                        "is_table": is_table
                    }
                })
                
        return chunks


# --- PIPELINE CONTROLLER ---

class RAGPipeline:
    """Manages parsing, chunking, dense vector indexing, BM25 creation, search, and LLM answering."""
    
    @staticmethod
    def extract_graph_data(text: str) -> list:
        """Uses OpenRouter LLM or local Ollama fallback to extract Knowledge Graph triplets from text."""
        global _openrouter_rate_limited
        if not OPENROUTER_API_KEY or _openrouter_rate_limited:
            use_ollama = True
            
        if not use_ollama:
            prompt = f"""You are a Knowledge Graph extractor.
Given the following text, extract all entities and the relationships between them.
Return the data EXCLUSIVELY as a JSON array of objects. 
Each object must have exactly three string fields: "subject", "relation", "object".
Do NOT return anything else, no markdown, no explanations.

Text:
{text}"""
            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": OPENROUTER_MODEL_NAME,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
                "response_format": {"type": "json_object"}
            }
            try:
                resp = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=(5, 15))
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"].strip()
                    if content.startswith("```json"):
                        content = content[7:]
                    if content.endswith("```"):
                        content = content[:-3]
                    
                    parsed = json.loads(content)
                    if isinstance(parsed, dict):
                        if "subject" in parsed and "object" in parsed:
                            return [parsed]
                        for k, v in parsed.items():
                            if isinstance(v, list):
                                return v
                        # Check for dictionary of dictionaries (Ollama format fallback)
                        triplets = []
                        for k, v in parsed.items():
                            if isinstance(v, dict) and "subject" in v and "object" in v:
                                triplets.append(v)
                        if triplets:
                            return triplets
                    return parsed if isinstance(parsed, list) else []
                else:
                    print(f"OpenRouter returned status {resp.status_code}. Setting rate limit flag and falling back to Ollama.")
                    _openrouter_rate_limited = True
                    use_ollama = True
            except Exception as e:
                print(f"Graph extraction via OpenRouter failed: {e}. Setting rate limit flag and falling back to Ollama.")
                _openrouter_rate_limited = True
                use_ollama = True

        if use_ollama:
            try:
                client = ollama.Client(host=OLLAMA_API_URL)
                prompt = f"""You are a Knowledge Graph extractor.
Given the following text, extract all entities and the relationships between them.
Return the data EXCLUSIVELY as a JSON array of objects. 
Each object must have exactly three string fields: "subject", "relation", "object".
Do NOT return anything else, no markdown, no explanations.

Text:
{text}"""
                resp = client.chat(
                    model=OLLAMA_MODEL_NAME,
                    messages=[{"role": "user", "content": prompt}],
                    options={"temperature": 0.0},
                    format="json"
                )
                content = resp["message"]["content"].strip()
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    if "subject" in parsed and "object" in parsed:
                        return [parsed]
                    for k, v in parsed.items():
                        if isinstance(v, list):
                            return v
                    # Check for dictionary of dictionaries
                    triplets = []
                    for k, v in parsed.items():
                        if isinstance(v, dict) and "subject" in v and "object" in v:
                            triplets.append(v)
                    if triplets:
                        return triplets
                return parsed if isinstance(parsed, list) else []
            except Exception as e:
                print(f"Graph extraction via Ollama failed: {e}")
        return []

    @staticmethod
    def extract_entities(query: str) -> list:
        """Uses OpenRouter LLM or local Ollama fallback to extract key entities from a user query for Graph search."""
        global _openrouter_rate_limited
        use_ollama = False
        if not OPENROUTER_API_KEY or _openrouter_rate_limited:
            use_ollama = True

        if not use_ollama:
            prompt = f"""Extract the main entities (names, concepts, places) from this query.
Return EXCLUSIVELY a JSON object with an "entities" key containing an array of strings. Do not return anything else.

Query: "{query}" """
            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": OPENROUTER_MODEL_NAME,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
                "response_format": {"type": "json_object"}
            }
            try:
                resp = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=(5, 15))
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"].strip()
                    if content.startswith("```json"):
                        content = content[7:]
                    if content.endswith("```"):
                        content = content[:-3]
                    parsed = json.loads(content)
                    if isinstance(parsed, list):
                        return parsed
                    elif isinstance(parsed, dict):
                        for k, v in parsed.items():
                            if isinstance(v, list):
                                return v
                else:
                    print(f"OpenRouter entity extraction returned status {resp.status_code}. Setting rate limit flag and falling back to Ollama.")
                    _openrouter_rate_limited = True
                    use_ollama = True
            except Exception:
                _openrouter_rate_limited = True
                use_ollama = True

        if use_ollama:
            try:
                client = ollama.Client(host=OLLAMA_API_URL)
                prompt = f"""Extract the main entities (names, concepts, places) from this query.
Return EXCLUSIVELY a JSON object with an "entities" key containing an array of strings. Do not return anything else.

Query: "{query}" """
                resp = client.chat(
                    model=OLLAMA_MODEL_NAME,
                    messages=[{"role": "user", "content": prompt}],
                    options={"temperature": 0.0},
                    format="json"
                )
                content = resp["message"]["content"].strip()
                parsed = json.loads(content)
                if isinstance(parsed, list):
                    return parsed
                elif isinstance(parsed, dict):
                    for k, v in parsed.items():
                        if isinstance(v, list):
                            return v
            except Exception as e:
                print(f"Entity extraction via Ollama failed: {e}")
        return []
    
    @staticmethod
    def create_index(file_id: str, file_path: str) -> List[Dict[str, Any]]:
        """Parses a file, chunks it, generates embeddings, creates indices, and saves everything."""
        # 1. Parse file
        raw_text = parse_document(file_path)
        
        # 2. Chunk document
        chunker = SmartChunker()
        chunks = chunker.split_text(raw_text)

        if not chunks:
            # Create a fallback chunk if empty
            chunks = [{"content": "Empty file contents.", "metadata": {"is_table": False}}]
            
        chunk_texts = [c["content"] for c in chunks]
        
        # 3. Generate dense vectors
        embedder = get_embedding_model()
        print(f"Generating embeddings for {len(chunk_texts)} chunks...")
        embeddings = embedder.encode(chunk_texts, convert_to_numpy=True).tolist()
        
        # 4. Upsert into ChromaDB
        ids = [f"{file_id}_{i}" for i in range(len(chunk_texts))]
        metadatas = [{"file_id": file_id} for _ in range(len(chunk_texts))]
        
        chroma_collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=chunk_texts,
            metadatas=metadatas
        )
        
        # 5. Build and save BM25 index (for hybrid combination)
        tokenized_chunks = [txt.lower().split() for txt in chunk_texts]
        bm25 = BM25Okapi(tokenized_chunks)
        
        bm25_path = os.path.join(INDEX_DIR, f"{file_id}.bm25.pkl")
        with open(bm25_path, "wb") as f:
            pickle.dump({
                "tokenized": tokenized_chunks,
                "bm25_obj": bm25
            }, f)
            
        print(f"Vector store and BM25 index built successfully for: {file_id}")
        return chunks

    @staticmethod
    def build_graph_index(file_id: str, chunks: List[Dict[str, Any]]):
        """Builds and saves the NetworkX Knowledge Graph asynchronously."""
        print(f"[Worker] Building NetworkX Knowledge Graph for {file_id}...")
        knowledge_graph = nx.DiGraph()
        # Process all non-table chunks to build a complete graph using OpenRouter/Ollama
        non_table_chunks = [c for c in chunks if not c.get("metadata", {}).get("is_table", False)]
        
        # Batch chunks to speed up graph building by ~5x
        batch_size = 5
        total_chunks = len(non_table_chunks)
        for i in range(0, total_chunks, batch_size):
            batch = non_table_chunks[i:i+batch_size]
            combined_content = "\\n\\n".join([c["content"] for c in batch])
            
            triplets = RAGPipeline.extract_graph_data(combined_content)
            for item in triplets:
                if isinstance(item, dict):
                    subj = item.get("subject")
                    rel = item.get("relation")
                    obj = item.get("object")
                    if subj and rel and obj:
                        knowledge_graph.add_edge(str(subj).strip(), str(obj).strip(), relation=str(rel).strip())
            
            # Update progress
            from backend.app.storage import update_graph_progress
            progress = int(min(100, ((i + batch_size) / max(1, total_chunks)) * 100))
            update_graph_progress(file_id, progress)
                            
        graph_path = os.path.join(INDEX_DIR, f"{file_id}.graph.pkl")
        with open(graph_path, "wb") as f:
            pickle.dump(knowledge_graph, f)
            
        # Export interactive HTML diagram to Desktop
        try:
            from pyvis.network import Network
            from backend.app.storage import get_file
            
            file_meta = get_file(file_id)
            filename = file_meta.get("filename", file_id) if file_meta else file_id
            base_name = os.path.splitext(filename)[0]
            
            diagram_dir = os.path.expanduser("~/Desktop/Graph_Diagrams")
            os.makedirs(diagram_dir, exist_ok=True)
            diagram_path = os.path.join(diagram_dir, f"{base_name}_graph.html")
            
            # Create beautiful dark-themed pyvis network
            net = Network(height="100vh", width="100%", bgcolor="#0f172a", font_color="white", directed=True, cdn_resources="in_line")
            net.from_nx(knowledge_graph)
            
            # Configure premium physics and styles
            net.set_options("""
            var options = {
              "nodes": {
                "shape": "dot",
                "scaling": {"min": 10, "max": 30},
                "font": {"size": 14, "face": "Inter, sans-serif"},
                "color": {"border": "#3b82f6", "background": "#1e293b", "highlight": {"border": "#60a5fa", "background": "#334155"}}
              },
              "edges": {
                "color": {"color": "#475569", "highlight": "#94a3b8"},
                "smooth": {"type": "dynamic"}
              },
              "physics": {
                "forceAtlas2Based": {"gravitationalConstant": -100, "springLength": 200},
                "minVelocity": 0.75,
                "solver": "forceAtlas2Based"
              }
            }
            """)
            net.save_graph(diagram_path)
            print(f"[Worker] Interactive Graph diagram saved to {diagram_path}")
        except Exception as e:
            print(f"[Worker] Failed to export pyvis graph diagram: {e}")
            
        print(f"[Worker] Graph built successfully for: {file_id}")

    @staticmethod
    def retrieve(file_id: str, db_chunks: List[dict], query: str, top_k: int = 15, top_p: int = 5, skip_reranking: bool = False) -> List[Dict[str, Any]]:
        """Retrieves using isolated ChromaDB + BM25 Hybrid scores followed by CrossEncoder reranking."""
        bm25_path = os.path.join(INDEX_DIR, f"{file_id}.bm25.pkl")
        
        if not os.path.exists(bm25_path):
            raise FileNotFoundError(f"BM25 Index for file {file_id} was not found. Try re-indexing.")
            
        # Reconstruct chunks list in correct order
        chunk_texts = [c["content"] for c in db_chunks]
        total_vectors = len(chunk_texts)
        search_k = min(top_k, total_vectors)
        
        # --- A. CHROMADB SEMANTIC SEARCH ---
        embedder = get_embedding_model()
        query_vector = embedder.encode(query, convert_to_numpy=True).tolist()
        
        results = chroma_collection.query(
            query_embeddings=[query_vector],
            n_results=search_k,
            where={"file_id": file_id}
        )
        
        semantic_scores = {}
        if results and results["ids"] and results["ids"][0]:
            ids = results["ids"][0]
            distances = results["distances"][0]
            for id_str, dist in zip(ids, distances):
                try:
                    idx = int(id_str.split("_")[-1])
                    semantic_scores[idx] = float(1.0 / (1.0 + dist))
                except:
                    continue
            
        # --- B. BM25 KEYWORD SEARCH ---
        with open(bm25_path, "rb") as f:
            bm25_data = pickle.load(f)
        
        bm25_obj = bm25_data["bm25_obj"]
        tokenized_query = query.lower().split()
        bm25_raw_scores = bm25_obj.get_scores(tokenized_query)
        
        # Normalize BM25 keyword scores (0 to 1)
        max_bm25 = max(bm25_raw_scores) if len(bm25_raw_scores) > 0 else 0
        denominator = max(max_bm25, 5.0) # Prevent inflating weak keyword matches
        bm25_scores = {}
        for idx, score in enumerate(bm25_raw_scores):
            bm25_scores[idx] = float(score / denominator) if denominator > 0 else 0.0
            
        # --- C. HYBRID COMBINATION ---
        hybrid_results = []
        for idx in range(total_vectors):
            s_score = semantic_scores.get(idx, 0.0)
            k_score = bm25_scores.get(idx, 0.0)
            
            # Hybrid score arithmetic: 0.7 * semantic + 0.3 * keyword
            hybrid_score = (0.7 * s_score) + (0.3 * k_score)
            
            hybrid_results.append({
                "idx": idx,
                "score": hybrid_score,
                "content": chunk_texts[idx],
                "metadata": db_chunks[idx].get("metadata", {})
            })
            
        # Sort and take top_k hybrid items
        hybrid_results = sorted(hybrid_results, key=lambda x: x["score"], reverse=True)[:top_k]
        
        # --- D. CROSS-ENCODER RERANKING ---
        if skip_reranking:
            reranked_results = hybrid_results
            for item in reranked_results:
                item["rerank_score"] = item["score"]
        else:
            reranker = get_reranker_model()
            pairs = [[query, item["content"]] for item in hybrid_results]
            
            if pairs:
                rerank_scores = reranker.predict(pairs)
                for idx, r_score in enumerate(rerank_scores):
                    hybrid_results[idx]["rerank_score"] = float(r_score)
                
                # Sort by rerank score descending
                reranked_results = sorted(hybrid_results, key=lambda x: x["rerank_score"], reverse=True)[:int(top_p) if top_p > 1 else max(1, int(len(hybrid_results) * top_p))]
                
                # Notebook strictly takes the top_p without dynamic pruning
                # (Reranked results are already sliced to top_p above)
            else:
                reranked_results = hybrid_results[:int(top_p) if top_p > 1 else max(1, int(len(hybrid_results) * top_p))]
                for item in reranked_results:
                    item["rerank_score"] = item["score"]
                
        # --- E. GRAPH RAG CONTEXT ---
        graph_path = os.path.join(INDEX_DIR, f"{file_id}.graph.pkl")
        if os.path.exists(graph_path):
            try:
                import networkx as nx
                import re
                with open(graph_path, "rb") as f:
                    knowledge_graph = pickle.load(f)
                
                graph_context_lines = []
                
                # Fast graph entity resolution (bypass slow LLM extraction at query time)
                if isinstance(knowledge_graph, nx.DiGraph):
                    query_lower = query.lower()
                    query_words = [w for w in re.findall(r'\w+', query_lower) if len(w) > 4]
                    
                    for node in knowledge_graph.nodes():
                        node_str = str(node).lower()
                        if len(node_str) < 3:
                            continue
                            
                        # Match if the exact node is in the query, or if any significant query word is in the node
                        if node_str in query_lower or any(w in node_str for w in query_words):
                            # Get all outgoing edges from this node
                            for _, target, data in knowledge_graph.out_edges(node, data=True):
                                rel = data.get("relation", "is related to")
                                graph_context_lines.append(f"{node} {rel} {target}")
                            # Get all incoming edges to this node
                            for src, _, data in knowledge_graph.in_edges(node, data=True):
                                rel = data.get("relation", "is related to")
                                graph_context_lines.append(f"{src} {rel} {node}")
                
                if graph_context_lines:
                    # Deduplicate and format
                    unique_lines = list(set(graph_context_lines))
                    graph_str = "KNOWLEDGE GRAPH CONTEXT:\n" + "\n".join(unique_lines)
                    # Append as a high-scoring synthetic chunk
                    reranked_results.insert(0, {
                        "idx": -1,
                        "score": 1.0,
                        "rerank_score": 1.0,
                        "content": graph_str,
                        "metadata": {"is_table": False, "Header 1": "Graph Search"}
                    })
            except Exception as e:
                print(f"Graph retrieval failed: {e}")
                
        return reranked_results

    @staticmethod
    def construct_prompt(query: str, retrieved_chunks: List[dict]) -> str:
        """Assembles context-grounded string based on retrieved contexts."""
        contexts = []
        for idx, item in enumerate(retrieved_chunks):
            # Check for table
            prefix = "[TABLE]" if item.get("metadata", {}).get("is_table", False) else "[TEXT]"
            contexts.append(f"--- Context Segment {idx + 1} {prefix} ---\n{item['content']}")
            
        return "\n\n".join(contexts)

    @staticmethod
    def ask_ollama_stream(query: str, context_str: str, provider: str = "ollama", openrouter_key: str = None, history: list = None):
        """Streams assistant response tokens from either OpenRouter or Local Ollama based on user preference."""
        
        system_instruction = """You are ContextIQ, a strict, factual enterprise AI assistant.
You MUST answer the user's question using ONLY the provided context segments. 
CRITICAL RULES:
1. Do NOT use outside knowledge or hallucinate data, numbers, or tables. 
2. If the user asks for data from a specific table (e.g. "Table 6"), carefully read the context. Note that PDF parsing may cause table titles to lack spaces (e.g., "table 6:ablations..."). The markdown data immediately following it IS the requested table.
3. If the answer is not in the provided context, explicitly state "I cannot find the answer in the provided documents."
"""

        # Build messages array including history
        messages_array = [{"role": "system", "content": system_instruction}]
        
        if history:
            for msg in history[-4:]: # Keep last 4 messages for context window
                messages_array.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
                
        # Bundle the retrieved contexts directly into the final user prompt to force maximum attention
        final_user_prompt = f"""You are a research paper assistant.

Answer ONLY using the provided context.

Format the answer using:
- clear paragraphs
- bullet points
- readable structure

Your task:
- summarize accurately
- explain experiments clearly
- include datasets
- include evaluation methodology
- include findings where available

Do NOT hallucinate.
Do NOT invent information.
CRITICAL RULE: When asked to display or extract a table, you MUST copy the rows and columns EXACTLY as they appear in the provided context. DO NOT omit rows. DO NOT invent numbers. If a cell is blank in the context, leave it blank. Do not mix data from different tables.
You MUST output the table strictly in Markdown table format (e.g. using `| column |` and `|---|---|`). DO NOT use bullet points for tables.

If information is incomplete,
explicitly mention it.

================ CONTEXT ================

{context_str}

================ QUESTION ================

{query}

================ ANSWER ================
"""
        messages_array.append({"role": "user", "content": final_user_prompt})

        # 1. OpenRouter Selection
        if provider == "openrouter":
            active_key = (openrouter_key or "").strip() or OPENROUTER_API_KEY
            if not active_key:
                yield "\n\n[ERROR: OpenRouter selected but no API Key found! Please set the OPENROUTER_API_KEY environment variable on the server.]"
                return
                
            print(f"[LLM] Directing stream request to OpenRouter model: {OPENROUTER_MODEL_NAME}")
            import requests, json
            headers = {
                "Authorization": f"Bearer {active_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/anushka/Isolated-RAG-Chatbot",
                "X-Title": "Antigravity Isolated RAG Chatbot"
            }
            payload = {
                "model": OPENROUTER_MODEL_NAME,
                "messages": messages_array,
                "stream": True
            }
            try:
                response = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    stream=True,
                    timeout=120
                )
                response.raise_for_status()
                for line in response.iter_lines():
                    if line:
                         decoded_line = line.decode('utf-8').strip()
                         if decoded_line.startswith('data: '):
                             data_str = decoded_line[6:]
                             if data_str.strip() == '[DONE]':
                                 break
                             try:
                                 data = json.loads(data_str)
                                 token = data['choices'][0]['delta'].get('content', '')
                                 if token:
                                     yield token
                             except Exception:
                                 pass
                return # Successfully streamed from OpenRouter
            except Exception as e:
                error_msg = str(e)
                print(f"[LLM] OpenRouter call failed: {error_msg}. Falling back to local Ollama model '{OLLAMA_MODEL_NAME}'...")
                yield f"\n\n> ⚠️ **OpenRouter API Error**: The requested cloud model is unavailable, rate-limited, or out of credits. Falling back to local {OLLAMA_MODEL_NAME} model...\n\n"
                
        # 2. Local Ollama Selection
        print(f"[LLM] Directing stream request to local Ollama model: {OLLAMA_MODEL_NAME}")
        try:
            client = ollama.Client(host=OLLAMA_API_URL)
            stream = client.chat(
                model=OLLAMA_MODEL_NAME,
                messages=messages_array,
                stream=True,
                options={
                    "num_predict": 2048,
                    "temperature": 0.1
                }
            )
            for chunk in stream:
                token = chunk.get("message", {}).get("content", "")
                if token:
                    yield token
        except Exception as e:
            yield f"\n\n[ERROR: Could not stream response from local Ollama. Make sure Ollama is running on your system! Error detail: {str(e)}]"

import pandas as pd
import sqlite3
import traceback

class StructuredDataPipeline:
    """Pipeline for processing and querying structured datasets using Text-to-SQL."""
    
    @staticmethod
    def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
        """Cleans dataframe by finding the actual header row and dropping empty rows/columns."""
        max_non_nulls = 0
        header_idx = 0
        for idx, row in df.head(20).iterrows():
            non_null_count = row.dropna().astype(str).str.strip().ne("").sum()
            if non_null_count > max_non_nulls:
                max_non_nulls = non_null_count
                header_idx = idx

        if max_non_nulls > 0 and header_idx > 0:
            # Set the header
            df.columns = df.iloc[header_idx]
            # Drop the header row and any rows above it
            df = df.iloc[header_idx + 1:].reset_index(drop=True)

        # Clean column names
        df.columns = [str(c).strip() if pd.notna(c) and str(c).strip() != "" else f"Column_{i}" for i, c in enumerate(df.columns)]

        # Drop columns that are entirely NaN
        df = df.dropna(axis=1, how='all')
        return df

    @staticmethod
    def load_single_file_to_db(file_path: str, file_type: str, table_name: str):
        """Loads a single CSV/Excel file into the persistent structured database."""
        from backend.app.config import STRUCTURED_DB_PATH
        conn = sqlite3.connect(STRUCTURED_DB_PATH)
        try:
            if file_type == "csv":
                df = pd.read_csv(file_path)
            elif file_type == "excel":
                df = pd.read_excel(file_path)
            else:
                raise ValueError(f"Unsupported structured file type: {file_type}")
            
            df = StructuredDataPipeline.clean_dataframe(df)
            df.to_sql(table_name, conn, index=False, if_exists='replace')
        except Exception as e:
            print(f"Warning: Failed to load {file_path} into table {table_name}: {e}")
        finally:
            conn.close()

    @staticmethod
    def get_schema_for_tables(conn: sqlite3.Connection, target_tables: list) -> str:
        """Extracts the schema for specific tables in the database, including sample data."""
        cursor = conn.cursor()
        
        schema_lines = []
        for table_name in target_tables:
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = cursor.fetchall()
            schema_lines.append(f"Table: {table_name}")
            col_names = []
            for col in columns:
                schema_lines.append(f"- {col[1]} ({col[2]})")
                col_names.append(col[1])
                
            # Fetch 3 sample rows
            try:
                cursor.execute(f"SELECT * FROM {table_name} LIMIT 3")
                sample_rows = cursor.fetchall()
                if sample_rows:
                    schema_lines.append(f"Sample data for {table_name}:")
                    schema_lines.append("| " + " | ".join(col_names) + " |")
                    schema_lines.append("|" + "|".join(["---"] * len(col_names)) + "|")
                    for row in sample_rows:
                        schema_lines.append("| " + " | ".join(str(item) for item in row) + " |")
            except Exception as e:
                pass
                
            schema_lines.append("")
        return "\n".join(schema_lines)

    @staticmethod
    def execute_read_only_query(conn: sqlite3.Connection, query: str) -> str:
        """Executes a SQL query safely (read-only)."""
        query = query.strip()
        if not query.lower().startswith("select"):
            return "Error: Only SELECT queries are allowed for security reasons."
            
        try:
            cursor = conn.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
            columns = [description[0] for description in cursor.description]
            
            if not rows:
                return "Query returned 0 results."
                
            # Format results as a markdown table
            header = "| " + " | ".join(columns) + " |"
            separator = "|" + "|".join(["---"] * len(columns)) + "|"
            
            result_lines = [header, separator]
            for row in rows[:50]: # Limit to 50 rows to avoid blowing up context
                result_lines.append("| " + " | ".join(str(item) for item in row) + " |")
                
            if len(rows) > 50:
                result_lines.append(f"*... and {len(rows) - 50} more rows truncated.*")
                
            return "\n".join(result_lines)
        except Exception as e:
            return f"SQL Execution Error: {str(e)}"

    @staticmethod
    def stream_sql_chat(query: str, chat_history: list, files_info: list, openrouter_key: str = None):
        """Streams the 2-step Text-to-SQL response."""
        yield "🔄 Analyzing structured dataset schema...\n\n"
        
        try:
            from backend.app.config import STRUCTURED_DB_PATH
            # 1. Connect to read-only persistent db
            conn = sqlite3.connect(f'file:{STRUCTURED_DB_PATH}?mode=ro', uri=True)
            table_names = [f.get("table_name", "dataset") for f in files_info]
            schema = StructuredDataPipeline.get_schema_for_tables(conn, table_names)
            
            # 2. Step 1: Generate SQL
            yield "🤖 Generating SQL query...\n\n"
            
            sql_prompt = f"""You are a SQLite expert. 
Given the following table schema and sample data:
{schema}

Note: If the columns are named "Unnamed", look at the sample data rows! The actual header might be in the first or second row of the data. Account for this in your query (e.g. filter out the header row and cast types appropriately).

CRITICAL RULES:
1. Map the user's terminology (like "field name" or "oil production") to the ACTUAL column names provided in the schema (like "Row Labels" or "Sum of Oil..."). 
2. Do NOT hallucinate column names. ONLY use the exact column names from the schema.
3. If a column name has spaces or special characters (e.g. "Row Labels"), you MUST enclose it in double quotes in your SQL query (e.g. SELECT "Row Labels" FROM {table_names[0]}).
4. If the user asks a general question like "what is this document about" or "summarize the data", do NOT just run `SELECT * LIMIT 5` as you will falsely assume the entire dataset is exactly like the first 5 rows! Instead, write a query to extract the FULL scope of the data: e.g., total row count, distinct counts of categorical columns, and min/max ranges for dates/numbers.

Write a valid SQLite SELECT query to answer this user question: "{query}"
Return ONLY the raw SQL query, no markdown blocks, no explanation. Do NOT wrap it in ```sql.
"""
            # Ask LLM for SQL
            sql_query = ""
            for token in RAGPipeline.ask_ollama_stream(
                query=sql_prompt, 
                context_str="", 
                provider="openrouter",
                openrouter_key=openrouter_key,
                history=[]
            ):
                sql_query += token
                
            sql_query = sql_query.strip().strip("`").replace("sql\n", "", 1).strip()
            
            yield f"**Generated Query:**\n```sql\n{sql_query}\n```\n\n"
            
            # 3. Step 2: Execute SQL
            yield "📊 Executing query against dataset...\n\n"
            query_results = StructuredDataPipeline.execute_read_only_query(conn, sql_query)
            
            # 4. Step 3: Formulate final answer
            answer_prompt = f"""You are a helpful data analyst.
The user asked: "{query}"

You ran a SQL query and got these results:
{query_results}

Formulate a conversational, clear answer to the user based on these results. 
If the results are a table, display the table clearly.
"""
            yield "💡 **Answer:**\n\n"
            for token in RAGPipeline.ask_ollama_stream(
                query=answer_prompt, 
                context_str="", 
                provider="openrouter",
                openrouter_key=openrouter_key,
                history=chat_history
            ):
                yield token
                
        except Exception as e:
            yield f"Error in structured data pipeline: {str(e)}\n\n"
        finally:
            if 'conn' in locals() and conn:
                conn.close()
