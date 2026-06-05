import os
import sys
import json
import sqlite3
import random
import requests
import time
from dotenv import load_dotenv
load_dotenv()

# Ensure imports work when executed from the project root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "data", "rag_chat.db")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

def generate_qa_pair(context_text):
    prompt = f"""
    Based on the following extracted context from a document, generate exactly ONE highly relevant, realistic question that a user might ask, and provide the correct, comprehensive answer based ONLY on the provided context.
    Return your response strictly in valid JSON format:
    {{
        "query": "<user question>",
        "expected_output": "<comprehensive answer>"
    }}
    
    Context:
    {context_text}
    """
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "openai/gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.5,
        "max_tokens": 500,
        "response_format": {"type": "json_object"}
    }
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=30)
            if response.status_code == 200:
                content = response.json()['choices'][0]['message']['content']
                # Sometimes models wrap json in markdown
                if content.startswith("```json"):
                    content = content[7:-3]
                elif content.startswith("```"):
                    content = content[3:-3]
                
                data = json.loads(content.strip())
                if "query" in data and "expected_output" in data:
                    return data
            else:
                print(f"API Error {response.status_code}: {response.text}")
                time.sleep(2)
        except Exception as e:
            print(f"Attempt {attempt+1} failed: {e}")
            time.sleep(2)
            
    return None

def main():
    if not OPENROUTER_API_KEY:
        print("ERROR: OPENROUTER_API_KEY environment variable is not set. Cannot generate dataset.")
        return

    print(f"Connecting to database at {DB_PATH}")
    if not os.path.exists(DB_PATH):
        print("ERROR: Database not found. Please upload documents first.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, file_id, content FROM chunks")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print("ERROR: No chunks found in database.")
        return
        
    cursor_files = sqlite3.connect(DB_PATH).cursor()
    cursor_files.execute("SELECT id, filename FROM files")
    files_map = {row[0]: row[1] for row in cursor_files.fetchall()}

    print(f"Loaded {len(rows)} total chunks from DB.")
    
    # Shuffle and pick chunks to ensure variety
    random.seed(42)
    random.shuffle(rows)
    
    target_count = 30
    dataset = []
    
    print(f"Generating {target_count} QA pairs using openai/gpt-4o-mini...")
    
    for row in rows:
        if len(dataset) >= target_count:
            break
            
        chunk_id, file_id, chunk_text = row
        file_name = files_map.get(file_id, "Unknown File")
        
        # Skip chunks that are too small to have meaningful QA
        if len(chunk_text.strip()) < 100:
            continue
            
        print(f"[{len(dataset)+1}/{target_count}] Processing chunk from {file_name}...")
        qa_data = generate_qa_pair(chunk_text)
        
        if qa_data:
            dataset.append({
                "query": qa_data["query"],
                "expected_output": qa_data["expected_output"],
                "file_id": file_id,
                "file_name": file_name
            })
            
            # Save incrementally
            with open("evaluation/test_dataset.json", "w") as f:
                json.dump(dataset, f, indent=2)
                
            time.sleep(1) # Be nice to the API

    print(f"\nSuccessfully generated {len(dataset)} QA pairs.")
    print("Saved to evaluation/test_dataset.json")

if __name__ == "__main__":
    os.makedirs("evaluation", exist_ok=True)
    main()
