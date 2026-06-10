import os
import sqlite3
import json
import uuid
from datetime import datetime
from backend.app.config import DB_PATH

def get_db_connection():
    """Establishes a connection to the SQLite database with dictionary rows."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the SQLite tables if they do not exist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Files Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_type TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            status TEXT NOT NULL,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 2. Chunks Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id TEXT PRIMARY KEY,
            file_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            metadata TEXT NOT NULL,
            FOREIGN KEY (file_id) REFERENCES files (id) ON DELETE CASCADE
        )
    """)
    
    # 3. Chat Sessions Table (1-to-1 with files)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id TEXT PRIMARY KEY,
            file_id TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (file_id) REFERENCES files (id) ON DELETE CASCADE
        )
    """)
    
    # 4. Messages Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL, -- 'user' or 'assistant'
            content TEXT NOT NULL,
            sources TEXT, -- JSON string containing source citations (chunks, filenames, scores)
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES chat_sessions (id) ON DELETE CASCADE
        )
    """)
    
    # 5. Collections Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS collections (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 6. Collection Files Mapping
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS collection_files (
            collection_id TEXT NOT NULL,
            file_id TEXT NOT NULL,
            PRIMARY KEY (collection_id, file_id),
            FOREIGN KEY (collection_id) REFERENCES collections (id) ON DELETE CASCADE,
            FOREIGN KEY (file_id) REFERENCES files (id) ON DELETE CASCADE
        )
    """)
    
    # 7. Collection Chat Sessions
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS collection_sessions (
            id TEXT PRIMARY KEY,
            collection_id TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (collection_id) REFERENCES collections (id) ON DELETE CASCADE
        )
    """)
    
    # 8. Collection Messages
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS collection_messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            sources TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES collection_sessions (id) ON DELETE CASCADE
        )
    """)
    
    conn.commit()
    conn.close()

# --- FILE OPERATIONS ---

def add_file(file_id: str, filename: str, file_path: str, file_type: str, file_size: int) -> dict:
    """Inserts a new file metadata entry into the database in 'processing' status."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    now = datetime.utcnow().isoformat()
    cursor.execute("""
        INSERT INTO files (id, filename, file_path, file_type, file_size, status, uploaded_at)
        VALUES (?, ?, ?, ?, ?, 'processing', ?)
    """, (file_id, filename, file_path, file_type, file_size, now))
    
    conn.commit()
    conn.close()
    
    return {
        "id": file_id,
        "filename": filename,
        "file_path": file_path,
        "file_type": file_type,
        "file_size": file_size,
        "status": "processing",
        "uploaded_at": now
    }

def update_file_status(file_id: str, status: str):
    """Updates the status of an ingested file (ready or error)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE files SET status = ? WHERE id = ?", (status, file_id))
    conn.commit()
    conn.close()

def get_file(file_id: str) -> dict:
    """Fetches a single file entry."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM files WHERE id = ?", (file_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def list_files() -> list:
    """Lists all files stored in the database, ordered by upload date descending."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM files ORDER BY uploaded_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_file(file_id: str):
    """Deletes a file and all associated chunks, sessions, and messages from SQLite."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # SQLite foreign keys with ON DELETE CASCADE will handle associated chunks, sessions, and messages!
    # Ensure foreign key support is active
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute("DELETE FROM files WHERE id = ?", (file_id,))
    
    conn.commit()
    conn.close()

# --- CHUNK OPERATIONS ---

def add_chunks(file_id: str, chunks: list):
    """Inserts a batch of chunk dictionaries into the chunks table."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    rows = []
    for idx, c in enumerate(chunks):
        chunk_id = str(uuid.uuid4())
        meta_json = json.dumps(c.get("metadata", {}))
        rows.append((chunk_id, file_id, idx, c["content"], meta_json))
        
    cursor.executemany("""
        INSERT INTO chunks (id, file_id, chunk_index, content, metadata)
        VALUES (?, ?, ?, ?, ?)
    """, rows)
    
    conn.commit()
    conn.close()

def get_file_chunks(file_id: str) -> list:
    """Fetches all chunk texts for a specific file, in order."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT chunk_index, content, metadata 
        FROM chunks 
        WHERE file_id = ? 
        ORDER BY chunk_index ASC
    """, (file_id,))
    rows = cursor.fetchall()
    conn.close()
    return [{"chunk_index": r["chunk_index"], "content": r["content"], "metadata": json.loads(r["metadata"])} for r in rows]

# --- CHAT & SESSION OPERATIONS ---

def get_or_create_session(file_id: str) -> str:
    """Gets the unique chat session ID for a file. If it doesn't exist, creates one."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM chat_sessions WHERE file_id = ?", (file_id,))
    row = cursor.fetchone()
    
    if row:
        session_id = row["id"]
    else:
        session_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        cursor.execute("INSERT INTO chat_sessions (id, file_id, created_at) VALUES (?, ?, ?)", (session_id, file_id, now))
        conn.commit()
        
    conn.close()
    return session_id

def add_message(session_id: str, role: str, content: str, sources: list = None) -> dict:
    """Appends a user or assistant message to the session."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    message_id = str(uuid.uuid4())
    sources_str = json.dumps(sources) if sources else None
    now = datetime.utcnow().isoformat()
    
    cursor.execute("""
        INSERT INTO messages (id, session_id, role, content, sources, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (message_id, session_id, role, content, sources_str, now))
    
    conn.commit()
    conn.close()
    
    return {
        "id": message_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "sources": sources,
        "created_at": now
    }

def get_session_messages(session_id: str) -> list:
    """Fetches all message objects in historical order for a session."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, role, content, sources, created_at 
        FROM messages 
        WHERE session_id = ? 
        ORDER BY created_at ASC
    """, (session_id,))
    rows = cursor.fetchall()
    conn.close()
    
    messages = []
    for r in rows:
        messages.append({
            "id": r["id"],
            "role": r["role"],
            "content": r["content"],
            "sources": json.loads(r["sources"]) if r["sources"] else None,
            "created_at": r["created_at"]
        })
    return messages

def clear_chat_history(file_id: str):
    """Clears all chat history associated with a specific file."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get session ID
    cursor.execute("SELECT id FROM chat_sessions WHERE file_id = ?", (file_id,))
    row = cursor.fetchone()
    if row:
        session_id = row["id"]
        cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.commit()
        
    conn.close()

# --- COLLECTION OPERATIONS ---

def create_collection(collection_id: str, name: str) -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute("INSERT INTO collections (id, name, created_at) VALUES (?, ?, ?)", (collection_id, name, now))
    conn.commit()
    conn.close()
    return {"id": collection_id, "name": name, "created_at": now}

def list_collections() -> list:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM collections ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_collection(collection_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
    conn.commit()
    conn.close()

def add_file_to_collection(collection_id: str, file_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO collection_files (collection_id, file_id) VALUES (?, ?)", (collection_id, file_id))
        conn.commit()
    except Exception:
        pass # Already exists
    finally:
        conn.close()

def remove_file_from_collection(collection_id: str, file_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM collection_files WHERE collection_id = ? AND file_id = ?", (collection_id, file_id))
    conn.commit()
    conn.close()

def get_collection_files(collection_id: str) -> list:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT f.* 
        FROM files f
        JOIN collection_files cf ON f.id = cf.file_id
        WHERE cf.collection_id = ?
    """, (collection_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_or_create_collection_session(collection_id: str) -> str:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM collection_sessions WHERE collection_id = ?", (collection_id,))
    row = cursor.fetchone()
    if row:
        session_id = row["id"]
    else:
        session_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        cursor.execute("INSERT INTO collection_sessions (id, collection_id, created_at) VALUES (?, ?, ?)", (session_id, collection_id, now))
        conn.commit()
    conn.close()
    return session_id

def add_collection_message(session_id: str, role: str, content: str, sources: list = None) -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    msg_id = str(uuid.uuid4())
    sources_str = json.dumps(sources) if sources else None
    now = datetime.utcnow().isoformat()
    cursor.execute("""
        INSERT INTO collection_messages (id, session_id, role, content, sources, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (msg_id, session_id, role, content, sources_str, now))
    conn.commit()
    conn.close()
    return {"id": msg_id, "session_id": session_id, "role": role, "content": content, "sources": sources, "created_at": now}

def get_collection_messages(session_id: str) -> list:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM collection_messages WHERE session_id = ? ORDER BY created_at ASC", (session_id,))
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r["id"], "role": r["role"], "content": r["content"], "sources": json.loads(r["sources"]) if r["sources"] else None, "created_at": r["created_at"]} for r in rows]
