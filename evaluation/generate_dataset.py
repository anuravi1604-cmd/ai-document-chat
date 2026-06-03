import os, json, sqlite3, requests, random
from dotenv import load_dotenv

load_dotenv(".env")
api_key = os.getenv("OPENROUTER_API_KEY")

conn = sqlite3.connect("backend/data/rag_chat.db")
cursor = conn.cursor()

cursor.execute("SELECT id, filename FROM files WHERE status='ready'")
files = cursor.fetchall()

test_cases = []
if files:
    queries_per_file = (30 // len(files)) + 2

    for fid, fname in files:
        cursor.execute("SELECT content FROM chunks WHERE file_id=?", (fid,))
        chunks = [c[0] for c in cursor.fetchall()]
        if not chunks: continue
        
        chunk = random.choice(chunks)
        prompt = f"Given this context from '{fname}', generate a JSON list of exactly {queries_per_file} specific questions and their correct answers based ONLY on the context. Output ONLY valid JSON in this format: {{\"questions\": [{{\"query\": \"...\", \"expected_output\": \"...\"}}]}}\n\nContext:\n{chunk[:2000]}"
        
        try:
            import ollama
            client = ollama.Client(host='http://localhost:11434')
            res = client.chat(model='mistral', messages=[{'role': 'user', 'content': prompt}], format='json')
            data = json.loads(res['message']['content'])
            for q in data.get("questions", []):
                test_cases.append({
                    "query": q["query"],
                    "expected_output": q["expected_output"],
                    "file_name": fname
                })
                print(f"Generated Q for {fname}: {q['query']}")
        except Exception as e:
            print(f"Error for {fname}: {e}")
                
test_cases = test_cases[:30]
with open("evaluation/test_dataset.json", "w") as f:
    json.dump(test_cases, f, indent=2)
print(f"Saved {len(test_cases)} queries to evaluation/test_dataset.json.")
