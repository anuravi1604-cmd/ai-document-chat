import os
import uuid
import json
import shutil
from typing import Optional
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse
from pydantic import BaseModel

from app.config import UPLOAD_DIR, INDEX_DIR
from app.storage import (
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
    clear_chat_history
)
from app.pipeline import RAGPipeline

app = FastAPI(
    title="Antigravity AI Document Chat RAG Backend",
    description="Isolated multi-file Retrieval-Augmented Generation (RAG) backend engine",
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

# Startup Handler: initialize database schema
@app.on_event("startup")
def on_startup():
    print("Initializing RAG database schema...")
    init_db()
    print("Database schema initialized successfully.")

# Background Task to process document index asynchronously
def process_document_in_background(file_id: str, file_path: str):
    try:
        print(f"[Worker] Starting RAG indexing for file ID: {file_id}")
        # Build FAISS + BM25 and get chunks
        chunks = RAGPipeline.create_index(file_id, file_path)
        # Store chunks in database
        add_chunks_wrapper(file_id, chunks)
        # Mark file as ready
        update_file_status(file_id, "ready")
        print(f"[Worker] Document index built and stored for file ID: {file_id}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[Worker ERROR] Failed to index document {file_id}: {str(e)}")
        update_file_status(file_id, "error")

def add_chunks_wrapper(file_id: str, chunks: list):
    """Auxiliary to avoid import cycles / inline storage operation."""
    from app.storage import add_chunks
    add_chunks(file_id, chunks)


# --- API ENDPOINTS ---

class ChatRequest(BaseModel):
    query: str

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
def upload_document(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """Uploads a file, saves it, and starts RAG pipeline indexing in the background."""
    filename = file.filename
    ext = os.path.splitext(filename)[1].lower()
    
    if ext not in [".pdf", ".docx", ".txt", ".md", ".markdown"]:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{ext}'. Supported formats: PDF, DOCX, TXT, MD"
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
    file_type = "pdf" if ext == ".pdf" else "docx" if ext == ".docx" else "txt" if ext in [".txt", ".md", ".markdown"] else "unknown"
    
    # 2. Add metadata record in SQLite (processing status)
    try:
        file_meta = add_file(
            file_id=file_id,
            filename=filename,
            file_path=temp_file_path,
            file_type=file_type,
            file_size=file_size
        )
    except Exception as e:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        raise HTTPException(status_code=500, detail=f"Failed to write file metadata: {str(e)}")
        
    # 3. Trigger background worker for document parsing, chunking, and embedding
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
            
    # 2. Delete RAG index stores
    faiss_path = os.path.join(INDEX_DIR, f"{file_id}.faiss")
    bm25_path = os.path.join(INDEX_DIR, f"{file_id}.bm25.pkl")
    
    if os.path.exists(faiss_path):
        try:
            os.remove(faiss_path)
        except Exception as e:
            print(f"Warning: Failed to delete FAISS index {faiss_path}: {e}")
            
    if os.path.exists(bm25_path):
        try:
            os.remove(bm25_path)
        except Exception as e:
            print(f"Warning: Failed to delete BM25 index {bm25_path}: {e}")
            
    # 3. Clean database (SQLite ON DELETE CASCADE cleans chunks, sessions, and messages automatically!)
    try:
        delete_file(file_id)
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
async def chat_with_document(file_id: str, payload: ChatRequest):
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
        
    # 2. Retrieve top matching chunks using the hybrid FAISS + BM25 Rerank pipeline
    try:
        retrieved_chunks = RAGPipeline.retrieve(
            file_id=file_id,
            db_chunks=db_chunks,
            query=query,
            top_k=15, # Semantic + keyword pooled candidates
            top_p=5   # Rerank top outputs
        )
    except FileNotFoundError as fnf:
        raise HTTPException(status_code=404, detail=str(fnf))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Retrieval error: {str(e)}")
        
    # 3. Create persistent chat session for isolated chat context
    session_id = get_or_create_session(file_id)
    
    # 4. Save User Message in database
    add_message(session_id=session_id, role="user", content=query)
    
    # 5. Build prompt
    prompt = RAGPipeline.construct_prompt(query, retrieved_chunks)
    
    # 6. Stream SSE generator
    async def sse_event_generator():
        # Pre-format sources payload
        sources = []
        for idx, item in enumerate(retrieved_chunks):
            sources.append({
                "source_index": idx + 1,
                "content": item["content"],
                "score": float(item["score"]),
                "rerank_score": float(item.get("rerank_score", item["score"])),
                "is_table": bool(item.get("metadata", {}).get("is_table", False)),
                "header": item.get("metadata", {}).get("Header 1", "")
            })
            
        # A. Emit retrieved sources first
        yield f"event: sources\ndata: {json.dumps(sources)}\n\n"
        
        # B. Stream prompt generation tokens from Local Ollama (Mistral)
        ai_response_text = ""
        try:
            # We call this in a blocking-to-async thread context if required, but inside generator is fine
            for token in RAGPipeline.ask_ollama_stream(prompt):
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
