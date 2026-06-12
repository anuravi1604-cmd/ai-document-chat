import os
import json
import sqlite3
import random
import requests

from backend.app.config import OPENROUTER_API_KEY, OPENROUTER_MODEL_NAME
from backend.app.storage import get_file_chunks

FILE_ID = "e348aa35-9c3a-44e3-98e8-e226a2280595" # demodataset.pdf
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
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": OPENROUTER_MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"}
    }
    
    try:
        response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data)
        response.raise_for_status()
        content = response.json()['choices'][0]['message']['content']
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
    chunks = get_file_chunks(FILE_ID)
    if not chunks:
        print("No chunks found!")
        return
        
    random.shuffle(chunks)
    dataset = []
    
    print(f"Found {len(chunks)} chunks. Generating dataset of ~30 queries...")
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
