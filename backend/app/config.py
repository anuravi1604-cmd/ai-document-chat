import os

# Project root directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

# Storage folders
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
INDEX_DIR = os.path.join(DATA_DIR, "indexes")
DB_PATH = os.path.join(DATA_DIR, "rag_chat.db")

# Ensure directories exist
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(INDEX_DIR, exist_ok=True)

# AI Model Configuration
EMBEDDING_MODEL_NAME = "BAAI/bge-base-en-v1.5"
RERANKER_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
OLLAMA_MODEL_NAME = "mistral"
OLLAMA_API_URL = "http://localhost:11434"
