import os
import json
import pickle
import requests
import numpy as np
import faiss
from typing import List, Dict, Tuple, Any
from docx import Document as DocxDoc
from docling.document_converter import DocumentConverter
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer, CrossEncoder
from rank_bm25 import BM25Okapi
import ollama

from backend.app.config import (
    EMBEDDING_MODEL_NAME,
    RERANKER_MODEL_NAME,
    INDEX_DIR,
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL_NAME,
    OLLAMA_MODEL_NAME,
    OLLAMA_API_URL
)

# Global models cached inside memory to avoid loading on every query
_embedding_model = None
_reranker_model = None

def get_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        print(f"Loading embedding model: {EMBEDDING_MODEL_NAME}...")
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        print("Embedding model loaded successfully.")
    return _embedding_model

def get_reranker_model() -> CrossEncoder:
    global _reranker_model
    if _reranker_model is None:
        print(f"Loading reranker model: {RERANKER_MODEL_NAME}...")
        _reranker_model = CrossEncoder(RERANKER_MODEL_NAME)
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
        file_size = os.path.getsize(file_path)
        
        # 1. Detect if the PDF is scanned or has garbled font encodings
        is_scanned = True
        try:
            import pypdf
            with open(file_path, "rb") as f:
                reader = pypdf.PdfReader(f)
                total_text_len = 0
                num_pages = len(reader.pages)
                if num_pages > 0:
                    # Sample first 5 pages to determine if it is scanned (fast and highly accurate check)
                    pages_to_check = min(5, num_pages)
                    has_garbage = False
                    for i in range(pages_to_check):
                        page_text = reader.pages[i].extract_text()
                        if page_text:
                            total_text_len += len(page_text.strip())
                            # If extracted text is garbled/garbage, flag it immediately
                            if is_garbage_text(page_text):
                                has_garbage = True
                                break
                    
                    # If average character count is > 50 AND no page was flagged as garbage, it is text-based
                    if not has_garbage and (total_text_len / pages_to_check) > 50:
                        is_scanned = False
        except Exception as e:
            print(f"Error checking if PDF is scanned: {e}")
            is_scanned = True # fallback to scanned (safest) on error
            
        print(f"[Parser] PDF Analysis - Size: {file_size / (1024*1024):.2f}MB, Requires OCR (Scanned/Garbled): {is_scanned}")
        
        # 2. Route Text-based PDFs to high-speed pypdf

        if not is_scanned:
            print(f"[Parser] Parsing TEXT-BASED PDF with fast-path (pypdf): {file_path}")
            try:
                import pypdf
                text_parts = []
                with open(file_path, "rb") as f:
                    reader = pypdf.PdfReader(f)
                    for i, page in enumerate(reader.pages):
                        text = page.extract_text()
                        if text:
                            text_parts.append(f"## Page {i+1}\n\n{text}")
                return "\n\n".join(text_parts)
            except Exception as e:
                print(f"[Parser WARNING] Fast-path pypdf extraction failed, falling back to optimized Docling: {e}")
        
        # 3. Route Scanned PDFs or fallback through a highly optimized Docling pipeline
        # Disabling heavy visual/table structure analysis boosts conversion speed by 5x-10x on CPU.
        print(f"[Parser] Parsing PDF with optimized Docling pipeline. OCR Enabled: {is_scanned}")
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
        
        pipeline_options = PdfPipelineOptions()
        # Enable OCR only if it is actually a scanned PDF or has garbled fonts
        pipeline_options.do_ocr = is_scanned
        # Force OCR to run on the whole page, ignoring any corrupted or garbled embedded text layers
        pipeline_options.ocr_options.force_full_page_ocr = is_scanned
        # Turn off visual table structure extraction and page rendering (heavy CPU models)
        pipeline_options.do_table_structure = False
        pipeline_options.generate_page_images = False
        pipeline_options.generate_picture_images = False
        
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
        result = converter.convert(file_path)
        markdown_text = result.document.export_to_markdown()
        return markdown_text
        
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
    
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
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
        embeddings = embedder.encode(chunk_texts, convert_to_numpy=True)
        
        # 4. Build and save FAISS index FlatL2
        embedding_dim = embeddings.shape[1]
        faiss_index = faiss.IndexFlatL2(embedding_dim)
        faiss_index.add(np.array(embeddings).astype("float32"))
        
        faiss_path = os.path.join(INDEX_DIR, f"{file_id}.faiss")
        faiss.write_index(faiss_index, faiss_path)
        
        # 5. Build and save BM25 index
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
    def retrieve(file_id: str, db_chunks: List[dict], query: str, top_k: int = 15, top_p: int = 5) -> List[Dict[str, Any]]:
        """Retrieves using isolated FAISS + BM25 Hybrid scores followed by CrossEncoder reranking."""
        faiss_path = os.path.join(INDEX_DIR, f"{file_id}.faiss")
        bm25_path = os.path.join(INDEX_DIR, f"{file_id}.bm25.pkl")
        
        if not os.path.exists(faiss_path) or not os.path.exists(bm25_path):
            raise FileNotFoundError(f"Indexes for file {file_id} were not found. Try re-indexing.")
            
        # Reconstruct chunks list in correct order
        chunk_texts = [c["content"] for c in db_chunks]
        
        # --- A. FAISS SEMANTIC SEARCH ---
        embedder = get_embedding_model()
        query_vector = embedder.encode(query, convert_to_numpy=True).astype("float32").reshape(1, -1)
        
        faiss_index = faiss.read_index(faiss_path)
        total_vectors = faiss_index.ntotal
        
        # Limit search top_k to total chunks available
        search_k = min(top_k, total_vectors)
        distances, faiss_indices = faiss_index.search(query_vector, search_k)
        
        # Map indices to scores: score = 1 / (1 + L2_distance)
        semantic_scores = {}
        for dist, idx in zip(distances[0], faiss_indices[0]):
            if idx == -1:
                continue
            semantic_scores[int(idx)] = float(1.0 / (1.0 + dist))
            
        # --- B. BM25 KEYWORD SEARCH ---
        with open(bm25_path, "rb") as f:
            bm25_data = pickle.load(f)
        
        bm25_obj = bm25_data["bm25_obj"]
        tokenized_query = query.lower().split()
        bm25_raw_scores = bm25_obj.get_scores(tokenized_query)
        
        # Normalize BM25 keyword scores (0 to 1)
        max_bm25 = max(bm25_raw_scores) if len(bm25_raw_scores) > 0 else 0
        bm25_scores = {}
        for idx, score in enumerate(bm25_raw_scores):
            bm25_scores[idx] = float(score / max_bm25) if max_bm25 > 0 else 0.0
            
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
        reranker = get_reranker_model()
        pairs = [[query, item["content"]] for item in hybrid_results]
        
        if pairs:
            rerank_scores = reranker.predict(pairs)
            for idx, r_score in enumerate(rerank_scores):
                hybrid_results[idx]["rerank_score"] = float(r_score)
            
            # Sort by rerank score descending
            reranked_results = sorted(hybrid_results, key=lambda x: x["rerank_score"], reverse=True)[:top_p]
        else:
            reranked_results = hybrid_results[:top_p]
            for item in reranked_results:
                item["rerank_score"] = item["score"]
                
        return reranked_results

    @staticmethod
    def construct_prompt(query: str, retrieved_chunks: List[dict]) -> str:
        """Assembles context-grounded prompt based on retrieved contexts."""
        contexts = []
        for idx, item in enumerate(retrieved_chunks):
            # Check for table
            prefix = "[TABLE]" if item.get("metadata", {}).get("is_table", False) else "[TEXT]"
            contexts.append(f"--- Context Segment {idx + 1} {prefix} ---\n{item['content']}")
            
        context_str = "\n\n".join(contexts)
        
        prompt = f"""You are a helpful, professional AI Document Assistant.
Answer the user's question ONLY using the provided document contexts below.

Format your answer with:
- Clear paragraphs
- Bullet points where appropriate
- Markdown rendering (e.g. standard tables, code blocks)
- Source citations matching the numbers: e.g. [Source 1], [Source 2] at the end of statements where you pull facts.

================ RETRIEVED CONTEXTS ================
{context_str}

================ USER QUESTION ================
{query}

================ GENERATED RESPONSE ================
"""
        return prompt

    @staticmethod
    def ask_ollama_stream(prompt: str, provider: str = "ollama", openrouter_key: str = None):
        """Streams assistant response tokens from either OpenRouter or Local Ollama based on user preference."""
        # 1. OpenRouter Selection
        if provider == "openrouter":
            active_key = (openrouter_key or "").strip() or OPENROUTER_API_KEY
            
            print("Provider:", provider)
            print("Received key:", bool(openrouter_key))
            print("Active key:", bool(active_key))
            print("Model:", OPENROUTER_MODEL_NAME)

            if not active_key:
                yield "\n\n[ERROR: OpenRouter selected but no API Key found! Please paste your API Key in the settings panel at the top of the chat area or set the OPENROUTER_API_KEY environment variable on the server.]"
                return
                
            print(f"[LLM] Directing stream request to OpenRouter model: {OPENROUTER_MODEL_NAME}")
            headers = {
                "Authorization": f"Bearer {active_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/anushka/Isolated-RAG-Chatbot",
                "X-Title": "Antigravity Isolated RAG Chatbot"
            }
            payload = {
                "model": OPENROUTER_MODEL_NAME,
                "messages": [{"role": "user", "content": prompt}],
                "stream": True
            }
            try:
                response = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    stream=True,
                    timeout=30
                )
                if response.status_code != 200:
                    print("STATUS CODE:", response.status_code)

                    try:
                        print("ERROR JSON:", response.json())
                    except Exception:
                        print("ERROR TEXT:", response.text)

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
                yield f"\n\n[ERROR: OpenRouter API call failed. Error detail: {str(e)}]"
                return
                
        # 2. Local Ollama Selection
        print(f"[LLM] Directing stream request to local Ollama model: {OLLAMA_MODEL_NAME}")
        client = ollama.Client(host=OLLAMA_API_URL)
        try:
            stream = client.chat(
                model=OLLAMA_MODEL_NAME,
                messages=[{"role": "user", "content": prompt}],
                stream=True
            )
            for chunk in stream:
                token = chunk.get("message", {}).get("content", "")
                if token:
                    yield token
        except Exception as e:
            yield f"\n\n[ERROR: Could not stream response from local Ollama. Make sure Ollama is running on your system! Error detail: {str(e)}]"
