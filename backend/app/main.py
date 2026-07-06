import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["OMP_NUM_THREADS"] = "1"
import uuid
import json
import shutil
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.app.config import UPLOAD_DIR, INDEX_DIR
from backend.app.storage import (
    init_db,
    add_file,
    update_file_status,
    list_files,
    delete_file,
    get_file,
    get_file_chunks,
    get_or_create_session,
    add_message,
    get_session_messages,
    clear_chat_history,
    create_collection,
    update_collection,
    list_collections,
    delete_collection,
    add_file_to_collection,
    is_file_in_collection_by_name,
    remove_file_from_collection,
    get_collection_files,
    get_or_create_collection_session,
    add_collection_message,
    get_collection_messages
)
from backend.app.pipeline import RAGPipeline

app = FastAPI(
    title="ContextIQ Enterprise RAG API",
    description="AI-powered multi-document retrieval workspace",
    version="1.0.0"
)

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
from backend.app.config import BASE_DIR
# BASE_DIR is backend, but frontend is at same level as backend. 
# So we need to go up one level from backend, which is dirname(BASE_DIR)
PROJECT_ROOT = os.path.dirname(BASE_DIR)
STATIC_DIR = os.path.join(PROJECT_ROOT, "frontend", "static")
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(os.path.join(STATIC_DIR, "css"), exist_ok=True)
os.makedirs(os.path.join(STATIC_DIR, "js"), exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Startup Handler: initialize database schema
@app.on_event("startup")
def on_startup():
    print("Initializing RAG database schema...")
    init_db()
    print("Database schema initialized successfully.")

# Background Task to process document index asynchronously
def process_document_in_background(file_id: str, file_path: str):
    try:
        from backend.app.storage import get_file
        file_meta = get_file(file_id)
        file_type = file_meta.get("file_type") if file_meta else "unknown"

        if file_type in ["csv", "excel"]:
            print(f"[Worker] Bypassing FAISS indexing for structured file ID: {file_id}")
            update_file_status(file_id, "ready")
            return

        print(f"[Worker] Starting RAG indexing for file ID: {file_id}")
        # Build FAISS + BM25 and get chunks
        chunks = RAGPipeline.create_index(file_id, file_path)
        # Store chunks in database
        add_chunks_wrapper(file_id, chunks)
        # Mark file as ready
        update_file_status(file_id, "ready")
        
        # Save parsed chunks as a Markdown file on the Desktop
        try:
            filename = file_meta.get("filename", file_id) if file_meta else file_id
            md_dir = os.path.expanduser("~/Desktop/Parsed_Markdown_Files")
            os.makedirs(md_dir, exist_ok=True)
            
            # Use original filename but swap extension to .md
            base_name = os.path.splitext(filename)[0]
            md_path = os.path.join(md_dir, f"{base_name}.md")
            
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(f"# Parsed Content for: {filename}\n\n")
                for chunk in chunks:
                    f.write(f"--- Chunk {chunk.get('chunk_index', '')} ---\n\n")
                    f.write(chunk.get("content", ""))
                    f.write("\n\n")
            print(f"[Worker] Exported parsed markdown to {md_path}")
        except Exception as e:
            print(f"[Worker] Failed to export markdown to Desktop: {e}")
            
        print(f"[Worker] Document index built and stored for file ID: {file_id}")
        
        # 4. Asynchronous Graph Building using a dedicated detached thread
        # This prevents exhausting Starlette's API thread pool while Ollama processes chunk by chunk
        import threading
        print(f"[Worker] Starting ASYNC Graph indexing for file ID: {file_id} in detached thread")
        t = threading.Thread(target=RAGPipeline.build_graph_index, args=(file_id, chunks))
        t.daemon = True
        t.start()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[Worker ERROR] Failed to index document {file_id}: {str(e)}")
        with open("/Users/anushka/.gemini/antigravity/scratch/doc_chat_rag/error.log", "a") as f:
            f.write(f"ERROR for {file_id}:\n" + traceback.format_exc() + "\n")
        update_file_status(file_id, "error")

def add_chunks_wrapper(file_id: str, chunks: list):
    """Auxiliary to avoid import cycles / inline storage operation."""
    from backend.app.storage import add_chunks
    add_chunks(file_id, chunks)


# --- API ENDPOINTS ---

class ChatRequest(BaseModel):
    query: str
    provider: Optional[str] = "ollama"
    openrouter_key: Optional[str] = None
    top_k: Optional[int] = 5

@app.get("/", response_class=HTMLResponse)
def read_root():
    """Serves the premium single-page web app frontend directly at the root URL."""
    frontend_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "frontend",
        "index.html"
    )
    if os.path.exists(frontend_path):
        with open(frontend_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Frontend file index.html not found!</h1>", status_code=404)

@app.post("/api/files/upload")
def upload_document(
    background_tasks: BackgroundTasks, 
    file: UploadFile = File(...),
    collection_id: Optional[str] = Form(None)
):
    """Uploads a file, saves it, and starts RAG pipeline indexing in the background."""
    filename = file.filename
    
    if collection_id == "null":
        collection_id = None
        
    if collection_id:
        existing = next((f for f in get_collection_files(collection_id) if f["filename"] == filename), None)
        if existing:
            print(f"Overwriting file {filename} in collection {collection_id}")
            try: delete_document(existing["id"])
            except: pass
    else:
        existing = next((f for f in list_files() if f["filename"] == filename), None)
        if existing:
            print(f"Overwriting file {filename} in isolated workspace")
            try: delete_document(existing["id"])
            except: pass
    ext = os.path.splitext(filename)[1].lower()
    
    if ext not in [".pdf", ".docx", ".txt", ".md", ".markdown", ".csv", ".xlsx"]:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{ext}'. Supported formats: PDF, DOCX, TXT, MD, CSV, XLSX"

        )
        
    file_id = str(uuid.uuid4())
    temp_file_path = os.path.join(UPLOAD_DIR, f"{file_id}{ext}")
    
    # 1. Save uploaded file to disk
    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
        
    file_size = os.path.getsize(temp_file_path)
    
    # Map raw extension to clean type
    if ext == ".pdf":
        file_type = "pdf"
    elif ext == ".docx":
        file_type = "docx"
    elif ext in [".txt", ".md", ".markdown"]:
        file_type = "txt"
    elif ext == ".csv":
        file_type = "csv"
    elif ext == ".xlsx":
        file_type = "excel"
    else:
        file_type = "unknown"
    
    # 2. Add metadata record in SQLite (processing status)
    is_isolated = 0 if collection_id else 1
    try:
        file_meta = add_file(
            file_id=file_id,
            filename=filename,
            file_path=temp_file_path,
            file_type=file_type,
            file_size=file_size,
            is_isolated=is_isolated
        )
    except Exception as e:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        raise HTTPException(status_code=500, detail=f"Failed to write file metadata: {str(e)}")
        
    if collection_id:
        try:
            add_file_to_collection(collection_id, file_id)
        except Exception as e:
            print(f"Warning: Failed to add file {file_id} to collection {collection_id}: {e}")
        
    # 3. Trigger background worker for document parsing, chunking, and embedding
    if file_type in ["csv", "excel"]:
        try:
            from backend.app.pipeline import StructuredDataPipeline
            safe_table_name = f"dataset_{file_id.replace('-', '_')}"
            StructuredDataPipeline.load_single_file_to_db(temp_file_path, file_type, safe_table_name)
            update_file_status(file_id, "ready")
            return {
                "message": "Structured dataset uploaded and loaded into SQLite.",
                "file": file_meta
            }
        except Exception as e:
            update_file_status(file_id, "error")
            raise HTTPException(status_code=500, detail=f"Failed to load structured data: {str(e)}")
            
    # For unstructured data, use background tasks
    background_tasks.add_task(process_document_in_background, file_id, temp_file_path)
    
    return {
        "message": "File uploaded and queuing for RAG processing.",
        "file": file_meta
    }

@app.get("/api/files")
def list_documents():
    """Lists all files processed or in pipeline."""
    try:
        return list_files()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/files/{file_id}")
def get_document_details(file_id: str):
    """Fetches details of a single document."""
    doc = get_file(file_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc

@app.get("/api/files/{file_id}/view")
def view_document(file_id: str):
    """Views the raw uploaded document in the browser or downloads it."""
    doc = get_file(file_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    file_path = doc.get("file_path")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File on disk not found")
    
    # Detect media type based on file extension
    ext = os.path.splitext(doc.get("filename", ""))[1].lower()
    media_type = "application/octet-stream"
    if ext == ".pdf":
        media_type = "application/pdf"
    elif ext in [".txt", ".md", ".markdown"]:
        media_type = "text/plain"
    elif ext == ".docx":
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        
    return FileResponse(
        path=file_path,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{doc.get("filename")}"'}
    )

@app.delete("/api/files/{file_id}")
def delete_document(file_id: str):
    """Deletes uploaded file, its associated RAG index, and SQLite database traces."""
    doc = get_file(file_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    # 1. Delete source file
    file_path = doc.get("file_path")
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            print(f"Warning: Failed to delete file {file_path}: {e}")
            
    # 2. Delete from ChromaDB
    try:
        from backend.app.pipeline import chroma_collection
        chroma_collection.delete(where={"file_id": file_id})
    except Exception as e:
        print(f"Warning: Failed to delete ChromaDB records for {file_id}: {e}")
        
    # Delete BM25 index
    bm25_path = os.path.join(INDEX_DIR, f"{file_id}.bm25.pkl")
    if os.path.exists(bm25_path):
        try:
            os.remove(bm25_path)
        except Exception as e:
            print(f"Warning: Failed to delete BM25 index {bm25_path}: {e}")
            
    # Delete Graph index
    graph_path = os.path.join(INDEX_DIR, f"{file_id}.graph.pkl")
    if os.path.exists(graph_path):
        try:
            os.remove(graph_path)
        except Exception as e:
            print(f"Warning: Failed to delete Graph index {graph_path}: {e}")
            
    # Delete Desktop Artifacts
    filename = doc.get("filename")
    if filename:
        base_name = os.path.splitext(filename)[0]
        md_path = os.path.expanduser(f"~/Desktop/Parsed_Markdown_Files/{base_name}.md")
        if os.path.exists(md_path):
            try: os.remove(md_path)
            except: pass
            
        graph_html_path = os.path.expanduser(f"~/Desktop/Graph_Diagrams/{base_name}_graph.html")
        if os.path.exists(graph_html_path):
            try: os.remove(graph_html_path)
            except: pass
            
    # 3. Clean database (SQLite ON DELETE CASCADE cleans chunks, sessions, and messages automatically!)
    try:
        # Also drop the structured dataset table if it exists
        if doc.get("file_type") in ["csv", "excel"]:
            from backend.app.config import STRUCTURED_DB_PATH
            import sqlite3
            conn = sqlite3.connect(STRUCTURED_DB_PATH)
            try:
                safe_table_name = f"dataset_{file_id.replace('-', '_')}"
                conn.execute(f"DROP TABLE IF EXISTS {safe_table_name}")
                conn.commit()
            except Exception as e:
                print(f"Warning: Failed to drop structured table dataset_{file_id}: {e}")
            finally:
                conn.close()
                
        delete_file(file_id)
        return {"message": "Document deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database clean error: {str(e)}")
        
    return {"message": f"Document {doc['filename']} deleted successfully."}

@app.get("/api/files/{file_id}/messages")
def get_chat_history(file_id: str):
    """Fetches full conversational message history dedicated to this file's isolated workspace."""
    doc = get_file(file_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    if doc["status"] != "ready":
        return {"session_id": None, "messages": [], "status": doc["status"]}
        
    try:
        session_id = get_or_create_session(file_id)
        messages = get_session_messages(session_id)
        return {
            "session_id": session_id,
            "messages": messages,
            "status": "ready"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/files/{file_id}/clear")
def clear_history(file_id: str):
    """Clears conversational logs for this isolated document chat workspace."""
    doc = get_file(file_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        clear_chat_history(file_id)
        return {"message": "Chat history cleared successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/files/{file_id}/chat")
def chat_with_document(file_id: str, payload: ChatRequest):
    """Isolated hybrid retrieval and LLM context answering, streaming response via SSE."""
    doc = get_file(file_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    if doc["status"] != "ready":
        raise HTTPException(
            status_code=400,
            detail="Document is still processing or indexing failed. Please wait or upload again."
        )
        
    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")
        
    file_type = doc.get("file_type", "unknown")
    
    if file_type not in ["csv", "excel"]:
        # 1. Fetch file chunks from database
        try:
            db_chunks = get_file_chunks(file_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch document chunks: {str(e)}")
            
        if not db_chunks:
            raise HTTPException(
                status_code=404,
                detail="No document chunks found. Try re-uploading the file."
            )
        
    if file_type not in ["csv", "excel"]:
        # 2. Retrieve top matching chunks using the hybrid FAISS + BM25 Rerank pipeline
        try:
            top_p = 8 # Enforced from notebook
            top_candidates = 20 # Enforced from notebook
            
            retrieved_chunks = RAGPipeline.retrieve(
                file_id=file_id,
                db_chunks=db_chunks,
                query=query,
                top_k=top_candidates,
                top_p=top_p
            )
        except FileNotFoundError as fnf:
            raise HTTPException(status_code=404, detail=str(fnf))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Retrieval error: {str(e)}")
    else:
        retrieved_chunks = []
        
    file_type = doc.get("file_type", "unknown")
    
    # 3. Create persistent chat session for isolated chat context
    session_id = get_or_create_session(file_id)
    history = get_session_messages(session_id)
    
    # 4. Save User Message in database
    add_message(session_id=session_id, role="user", content=query)
    
    # --- STRUCTURED DATA ROUTING ---
    if file_type in ["csv", "excel"]:
        def structured_sse_event_generator():
            full_assistant_response = ""
            from backend.app.pipeline import StructuredDataPipeline
            try:
                files_info = [{
                    "file_path": doc.get("file_path"),
                    "file_type": file_type,
                    "table_name": f"dataset_{file_id.replace('-', '_')}"
                }]
                for token in StructuredDataPipeline.stream_sql_chat(
                    query=query, 
                    chat_history=history, 
                    files_info=files_info,
                    openrouter_key=payload.openrouter_key
                ):
                    full_assistant_response += token
                    yield f"data: {json.dumps(token)}\n\n"
            except Exception as e:
                yield f"data: {json.dumps(str(e))}\n\n"
            finally:
                add_message(session_id=session_id, role="assistant", content=full_assistant_response, sources=[])
                yield "data: [DONE]\n\n"
                
        return StreamingResponse(structured_sse_event_generator(), media_type="text/event-stream")
        
    # --- UNSTRUCTURED VECTOR RAG ROUTING ---
    # 5. Build context string
    context_str = RAGPipeline.construct_prompt(query, retrieved_chunks)
    
    # 6. Stream SSE generator
    def sse_event_generator():
        # Pre-format sources payload
        import math
        sources = []
        for idx, item in enumerate(retrieved_chunks):
            s_score = float(item.get("score", 0.0))
            if math.isnan(s_score): s_score = 0.0
            
            r_score = float(item.get("rerank_score", s_score))
            if math.isnan(r_score): r_score = 0.0
            
            sources.append({
                "source_index": idx + 1,
                "content": item.get("content", ""),
                "score": s_score,
                "rerank_score": r_score,
                "is_table": bool(item.get("metadata", {}).get("is_table", False)),
                "header": item.get("metadata", {}).get("Header 1", ""),
                "filename": item.get("metadata", {}).get("filename", "")
            })
            
        # A. Emit retrieved sources first
        yield f"event: sources\ndata: {json.dumps(sources)}\n\n"
        
        # B. Stream prompt generation tokens from Local Ollama (Mistral)
        ai_response_text = ""
        try:
            # We call this in a blocking-to-async thread context if required, but inside generator is fine
            for token in RAGPipeline.ask_ollama_stream(query, context_str, provider=payload.provider, openrouter_key=payload.openrouter_key, history=history):
                ai_response_text += token
                yield f"event: token\ndata: {json.dumps(token)}\n\n"
        except Exception as e:
            err_msg = f"[ERROR: Model streaming failed: {str(e)}]"
            ai_response_text += err_msg
            yield f"event: token\ndata: {json.dumps(err_msg)}\n\n"
            
        # C. Save AI Message & associated sources details to SQLite
        try:
            add_message(session_id=session_id, role="assistant", content=ai_response_text, sources=sources)
        except Exception as db_err:
            print(f"Error saving assistant message: {db_err}")
            
        # D. Yield final termination token
        yield "event: done\ndata: [DONE]\n\n"
        
    return StreamingResponse(sse_event_generator(), media_type="text/event-stream")

# --- COLLECTION ENDPOINTS ---

class CollectionRequest(BaseModel):
    name: str

@app.post("/api/collections")
def api_create_collection(payload: CollectionRequest):
    name_to_check = payload.name.strip().lower()
    existing_collections = list_collections()
    for col in existing_collections:
        if col["name"].strip().lower() == name_to_check:
            raise HTTPException(status_code=400, detail=f"A collection with the name '{payload.name}' already exists.")
            
    collection_id = str(uuid.uuid4())
    col = create_collection(collection_id, payload.name)
    return col

@app.put("/api/collections/{collection_id}")
def api_update_collection(collection_id: str, payload: CollectionRequest):
    name_to_check = payload.name.strip().lower()
    existing_collections = list_collections()
    for col in existing_collections:
        if col["name"].strip().lower() == name_to_check and col["id"] != collection_id:
            raise HTTPException(status_code=400, detail=f"A collection with the name '{payload.name}' already exists.")
    
    updated_col = update_collection(collection_id, payload.name)
    return updated_col

@app.get("/api/collections")
def api_list_collections():
    return list_collections()

@app.delete("/api/collections/{collection_id}")
def api_delete_collection(collection_id: str):
    delete_collection(collection_id)
    return {"message": "Collection deleted"}

class CollectionFileRequest(BaseModel):
    file_id: str

@app.post("/api/collections/{collection_id}/files")
def api_add_file_to_collection(collection_id: str, payload: CollectionFileRequest):
    file_meta = get_file(payload.file_id)
    if not file_meta:
        raise HTTPException(status_code=404, detail="Document not found")
        
    if is_file_in_collection_by_name(collection_id, file_meta["filename"]):
        raise HTTPException(
            status_code=400,
            detail=f"A file named '{file_meta['filename']}' is already in this collection."
        )
        
    try:
        add_file_to_collection(collection_id, payload.file_id)
        return {"message": "File added to collection"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/collections/{collection_id}/files/{file_id}")
def api_remove_file_from_collection(collection_id: str, file_id: str):
    remove_file_from_collection(collection_id, file_id)
    return {"message": "File removed from collection"}

@app.get("/api/collections/{collection_id}/files")
def api_get_collection_files(collection_id: str):
    return get_collection_files(collection_id)

@app.get("/api/collections/{collection_id}/messages")
def api_get_collection_messages(collection_id: str):
    session_id = get_or_create_collection_session(collection_id)
    messages = get_collection_messages(session_id)
    return {
        "session_id": session_id,
        "messages": messages,
        "status": "ready"
    }

@app.post("/api/collections/{collection_id}/chat")
def chat_with_collection(collection_id: str, payload: ChatRequest):
    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")
        
    # Get all files in collection
    files = get_collection_files(collection_id)
    if not files:
        raise HTTPException(status_code=400, detail="Collection is empty")
        
    # Check if all files are ready
    for f in files:
        if f["status"] != "ready":
            raise HTTPException(status_code=400, detail=f"File {f['filename']} is not ready.")
            
    # Route based on file types
    structured_files_info = []
    unstructured_files = []
    
    for f in files:
        if f.get("file_type") in ["csv", "excel"]:
            table_name = f"dataset_{f['id'].replace('-', '_')}"
            structured_files_info.append({
                "file_path": f.get("file_path"),
                "file_type": f.get("file_type"),
                "table_name": table_name
            })
        else:
            unstructured_files.append(f)
            
    if len(structured_files_info) > 0 and len(unstructured_files) > 0:
        raise HTTPException(status_code=400, detail="Hybrid querying across both structured and unstructured data in a single collection is not supported yet. Please separate them.")
        
    session_id = get_or_create_collection_session(collection_id)
    history = get_collection_messages(session_id)
    add_collection_message(session_id=session_id, role="user", content=query)
    
    # --- STRUCTURED DATA ROUTING ---
    if len(structured_files_info) > 0:
        def structured_collection_sse_event_generator():
            full_assistant_response = ""
            from backend.app.pipeline import StructuredDataPipeline
            try:
                for token in StructuredDataPipeline.stream_sql_chat(
                    query=query, 
                    chat_history=history, 
                    files_info=structured_files_info,
                    openrouter_key=payload.openrouter_key
                ):
                    full_assistant_response += token
                    yield f"data: {json.dumps(token)}\n\n"
            except Exception as e:
                yield f"data: {json.dumps(str(e))}\n\n"
            finally:
                add_collection_message(session_id=session_id, role="assistant", content=full_assistant_response, sources=[])
                yield "data: [DONE]\n\n"
        return StreamingResponse(structured_collection_sse_event_generator(), media_type="text/event-stream")

    # --- UNSTRUCTURED VECTOR RAG ROUTING ---
    # Pool results across all unstructured files
    all_retrieved_chunks = []
    top_p = 8 # Enforced notebook limit per file
    top_candidates = 20 # Enforced notebook limit per file
    
    for f in unstructured_files:
        file_id = f["id"]
        try:
            db_chunks = get_file_chunks(file_id)
            if db_chunks:
                file_chunks = RAGPipeline.retrieve(
                    file_id=file_id,
                    db_chunks=db_chunks,
                    query=query,
                    top_k=top_candidates,
                    top_p=top_p,
                    skip_reranking=True
                )
                for chunk in file_chunks:
                    if "metadata" not in chunk: chunk["metadata"] = {}
                    chunk["metadata"]["filename"] = f["filename"]
                all_retrieved_chunks.extend(file_chunks)
        except Exception as e:
            print(f"Retrieval error for file {file_id}: {e}")
            
    # Global Reranking for Collections
    # Sort all pooled chunks globally by hybrid score first
    all_retrieved_chunks.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    
    # Take up to 150 candidates overall for reranking to ensure no file's chunks are unfairly dropped
    candidates_to_rerank = all_retrieved_chunks[:150]
    
    from backend.app.pipeline import get_reranker_model
    reranker = get_reranker_model()
    pairs = [[query, item["content"]] for item in candidates_to_rerank]
    
    if pairs:
        rerank_scores = reranker.predict(pairs)
        for idx, r_score in enumerate(rerank_scores):
            candidates_to_rerank[idx]["rerank_score"] = float(r_score)
            
    # Sort by rerank score descending
    candidates_to_rerank.sort(key=lambda x: x.get("rerank_score", x.get("score", 0)), reverse=True)
    
    # Take the absolute Top 20 overall for collections to ensure coverage across multiple documents
    final_chunks = candidates_to_rerank[:20]
    
    # Save User Message was already done above

    
    # Build context string
    context_str = RAGPipeline.construct_prompt(query, final_chunks)
    
    # Stream SSE
    def sse_event_generator():
        import math
        sources = []
        for idx, item in enumerate(final_chunks):
            s_score = float(item.get("score", 0.0))
            if math.isnan(s_score): s_score = 0.0
            r_score = float(item.get("rerank_score", s_score))
            if math.isnan(r_score): r_score = 0.0
            sources.append({
                "source_index": idx + 1,
                "content": item["content"],
                "score": s_score,
                "rerank_score": r_score,
                "is_table": bool(item.get("metadata", {}).get("is_table", False)),
                "header": item.get("metadata", {}).get("Header 1", ""),
                "filename": item.get("metadata", {}).get("filename", "")
            })
            
        yield f"event: sources\ndata: {json.dumps(sources)}\n\n"
        
        ai_response_text = ""
        try:
            for token in RAGPipeline.ask_ollama_stream(query, context_str, provider=payload.provider, openrouter_key=payload.openrouter_key, history=history):
                ai_response_text += token
                yield f"event: token\ndata: {json.dumps(token)}\n\n"
        except Exception as e:
            err_msg = f"[ERROR: Model streaming failed: {str(e)}]"
            ai_response_text += err_msg
            yield f"event: token\ndata: {json.dumps(err_msg)}\n\n"
            
        try:
            add_collection_message(session_id=session_id, role="assistant", content=ai_response_text, sources=sources)
        except Exception as db_err:
            print(f"Error saving assistant message: {db_err}")
            
        yield "event: done\ndata: [DONE]\n\n"
        
    return StreamingResponse(sse_event_generator(), media_type="text/event-stream")

@app.post("/api/collections/{collection_id}/clear")
def clear_collection_chat_history(collection_id: str):
    """Clears conversational logs for this collection workspace."""
    from backend.app.storage import clear_collection_history
    try:
        clear_collection_history(collection_id)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
