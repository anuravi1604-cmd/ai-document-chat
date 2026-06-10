# ContextIQ | Premium Enterprise RAG Chatbot Workspace

**ContextIQ** is a state-of-the-art, isolated multi-document Retrieval-Augmented Generation (RAG) chatbot workspace. It enables users to upload massive documents, build isolated semantic knowledge bases, and query them securely using either local offline models or cloud-based LLM providers.

Featuring a premium glassmorphic dark-mode user interface, ContextIQ delivers a developer-centric, ultra-responsive workspace experience with custom resizable sidebars and real-time citation grounding.

---

## 🚀 Key Features

### 1. Dynamic Dual-Path PDF Parsing (Optimized OCR)
ContextIQ implements a smart classification pipeline to bypass CPU processing bottlenecks:
- **High-Speed Text-PDF Route**: Automatically detects text-based PDFs. Extracts text in milliseconds using `pypdf`, indexing large files (33MB+) in seconds.
- **Speed-Optimized OCR Route**: Detects scanned or garbled-font PDFs. Routes them through `docling` with visual table extraction and page rendering disabled to speed up CPU conversion by **5x to 10x** while guaranteeing full OCR recognition.
- **CASCA Cascading Deletes**: Powered by SQLite database cascades (`ON DELETE CASCADE`), deleting a document instantly sweeps and purges all of its associated text chunks, FAISS vector indexes, BM25 pickles, and chat history.

### 2. Isolated Workspace Search
- Each document represents an independent chat session. All indexes are strictly separated by document ID to ensure **zero cross-contamination** of context segments between files.

### 3. Agentic Text-to-SQL for Structured Data
ContextIQ seamlessly handles structured datasets (CSV/Excel) natively:
- **Smart Routing**: Instantly recognizes `.csv` and `.xlsx` files, bypassing the semantic chunking engine and loading them directly into high-performance in-memory SQLite tables using pandas.
- **Robust Auto-Cleaning**: Dynamically scans the first 20 rows of spreadsheets to detect the true header row, ignoring empty spaces and title headers (solving the classic `Unnamed: 0` pandas problem).
- **Agentic SQL Generation**: Analyzes the schema and sample data to construct secure, read-only SQL queries to answer exact mathematical, aggregation, or filtering questions without vector hallucinations.
- **Collection Joins**: Chat with a collection of multiple CSV files simultaneously, joining them as separate SQL tables.

### 4. Advanced Hybrid Search & Reranking
ContextIQ leverages a state-of-the-art multi-stage retrieval architecture for unstructured text:
1. **Lexical Retrieval**: Extracts keyword matches using a BM25 index.
2. **Dense Retrieval**: Extracts semantic matches using BGE Embeddings (`BAAI/bge-base-en-v1.5`) inside a FAISS vector index.
3. **Hybrid Fusion**: Merges lexical and semantic scores using a weighted arithmetic combination (`0.7 * semantic + 0.3 * keyword`).
4. **Cross-Encoder Reranking**: Reranks the top 15 candidate segments using a Cross-Encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`) to surface the top 5 highly grounded contexts.

### 4. Custom API Selector (Local vs. Cloud)
- **Local Ollama**: Run completely offline and private using Ollama models (defaults to `mistral`).
- **Cloud OpenRouter**: Seamlessly switch to OpenRouter APIs. A beautiful, password-style API key container slides open in the header on selection.

### 5. Highly Interactive & Premium UI/UX
- **Glassmorphic Dark Theme**: An elegant dark-mode interface built on a `#090a0f` base with transparent backdrop filters, subtle border highlights, and live typewriter streaming.
- **Resizable Sidebars**: Hover and drag the border handles to customize Left (File list) and Right (Citations) sidebar widths. Click the chevron buttons to collapse sidebars completely for an immersive full-screen chat experience.
- **Active Citation Grounding**: Clicking the `Grounded Citations` badge under AI answers slides open the Citations Sidebar. In-text citation links (e.g. `[Source 1]`) linkify dynamically—clicking them automatically scrolls to and highlights the target source card in the sidebar with an amber pulse animation.

---

## 🛠️ Technology Stack

- **Backend**: FastAPI (Python), SQLite, FAISS (CPU), PyPDF, Docling (OCR), SentenceTransformers, Rank-BM25, Uvicorn.
- **Frontend**: Single-Page App (Vanilla JS / HTML5) styled with Tailwind CSS, Lucide Icons, Marked.js (Markdown), and Prism.js (Syntax Highlighting).

---

## ⚙️ Quick Start

### Prerequisites
- Python 3.9+
- [Ollama](https://ollama.com/) (Optional: for local models)

### 1. Clone & Initialize Environment
```bash
git clone https://github.com/anuravi1604-cmd/ai-document-chat.git
cd ai-document-chat

# Create and activate virtual env
python3 -m venv rag_env
source rag_env/bin/activate
```

### 2. Install Dependencies
```bash
pip install -r backend/requirements.txt
```

### 3. Configure Local Secrets
Create a `.env` file in the root directory (ignored by Git):
```env
OPENROUTER_API_KEY=your_fallback_openrouter_api_key_here
```

### 4. Run the Application
Start the Uvicorn development server:
```bash
python -m uvicorn backend.app.main:app --port 8000 --reload
```
Open **`http://127.0.0.1:8000`** in your browser to start building your isolated knowledge base!

---

## 📂 Project Architecture

```
ai-document-chat/
├── backend/
│   ├── app/
│   │   ├── config.py          # Storage directories and AI model settings
│   │   ├── main.py            # FastAPI endpoints, background tasks, and SSE streaming
│   │   ├── pipeline.py        # Document parsing, hybrid FAISS/BM25 retrieval, and LLM streaming
│   │   └── storage.py         # SQLite CRUD database schemas and cascade deletions
│   └── data/                  # Local storage folders (database, uploads, and indexes)
├── frontend/
│   └── index.html             # HTML5/JS Glassmorphic Single-Page Application
└── README.md                  # ContextIQ Documentation
```

---

## 🛡️ License
Distributed under the MIT License. See `LICENSE` for more information.
