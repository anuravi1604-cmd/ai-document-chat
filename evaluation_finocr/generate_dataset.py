import os
import json
import sqlite3
import random
import requests

from backend.app.config import OPENROUTER_API_KEY, OPENROUTER_MODEL_NAME
from backend.app.storage import get_file_chunks

FILE_IDS = [
    "450a1c31-d431-4398-86f1-5cfb7e4650ee",
    "2ff1cbd9-c724-4c2d-9f13-c4e0c72b27ea",
    "498e5194-7c2a-4909-9565-f631f8481d82",
    "2aac5378-8f84-4d35-bf1f-ff88d11eac25"
]
DATASET_PATH = os.path.join(os.path.dirname(__file__), "test_dataset.json")

def generate_qa_pairs(text_chunk, num_pairs=2):
    prompt = f"""
    You are an expert dataset generator. Based on the following text chunk, generate {num_pairs} diverse, challenging questions and their exact correct answers.
    Output MUST be a valid JSON array of objects with keys 'query' and 'expected_output'.
    Example: [{{"query": "What is X?", "expected_output": "X is Y."}}]
    
    TEXT:
    {text_chunk}
    """
    
    headers = {
        "Content-Type": "application/json"
    }
    data = {
        "model": "mistral",
        "messages": [{"role": "user", "content": prompt}],
        "format": "json",
        "stream": False
    }
    
    try:
        response = requests.post("http://localhost:11434/api/chat", headers=headers, json=data)
        response.raise_for_status()
        content = response.json()['message']['content']
        # Handle potential markdown wrappers
        content = content.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(content)
        
        # Sometime LLM puts the array inside a dictionary key
        if isinstance(parsed, dict):
            for k, v in parsed.items():
                if isinstance(v, list):
                    return v
        return parsed
    except Exception as e:
        print(f"Error generating QA: {e}")
        return []

def main():
    print("Fetching chunks from DB...")
    chunks = []
    for fid in FILE_IDS:
        c = get_file_chunks(fid)
        if c:
            chunks.extend(c)
            
    if not chunks:
        print("No chunks found!")
        return
        
    random.shuffle(chunks)
    dataset = []
    
    print(f"Found {len(chunks)} chunks across {len(FILE_IDS)} files. Generating dataset of ~30 queries...")
    for chunk in chunks:
        text = chunk.get("content", "")
        if not text.strip(): continue
        
        print(f"Generating for chunk length {len(text)}... (current total: {len(dataset)})")
        pairs = generate_qa_pairs(text, 3)
        if isinstance(pairs, list):
            for p in pairs:
                if 'query' in p and 'expected_output' in p:
                    dataset.append(p)
        elif isinstance(pairs, dict) and 'query' in pairs and 'expected_output' in pairs:
            dataset.append(pairs)
                    
        if len(dataset) >= 30:
            break
            
    # Trim to exactly 30
    dataset = dataset[:30]
    print(f"Generated {len(dataset)} pairs. Saving to {DATASET_PATH}")
    
    with open(DATASET_PATH, 'w') as f:
        json.dump(dataset, f, indent=4)
        
    print("Done!")

if __name__ == "__main__":
    main()
