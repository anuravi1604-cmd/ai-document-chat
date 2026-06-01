import os
import sys
import json
import csv
import time
import argparse
import sqlite3
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from dotenv import load_dotenv

# Ensure we can import backend packages
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Load environmental variables from RAG .env
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "../.env")))

from backend.app.storage import get_file_chunks
from backend.app.pipeline import RAGPipeline

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../backend/data/rag_chat.db"))

# ==========================================
# 1. DEEPEVAL CUSTOM JUDGE LLM WRAPPER
# ==========================================
from deepeval.models import DeepEvalBaseLLM
from pydantic import BaseModel
import requests

class OpenRouterLLM(DeepEvalBaseLLM):
    """Custom DeepEval LLM evaluator leveraging the user's OpenRouter key with local Ollama fallback."""
    def __init__(self, model_name="openai/gpt-4o-mini"):
        self.model_name = model_name
        self.api_key = os.getenv("OPENROUTER_API_KEY")

    def get_model_name(self):
        return self.model_name

    def load_model(self):
        return self

    def generate(self, prompt: str, schema: BaseModel = None) -> str:
        if not self.api_key:
            print("[Evaluator LLM] No OPENROUTER_API_KEY found, falling back to local Ollama...")
            return self._fallback_ollama(prompt)
            
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/anuravi1604-cmd/ai-document-chat",
            "X-Title": "Antigravity DeepEval RAG Evaluator"
        }
        
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0
        }
        
        # Enforce structured output if schema requested
        if schema:
            payload["response_format"] = {"type": "json_object"}
            
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=90
            )
            if response.status_code != 200:
                print(f"[Evaluator LLM] OpenRouter returned status {response.status_code}. Falling back...")
                return self._fallback_ollama(prompt)
            
            res_json = response.json()
            return res_json['choices'][0]['message']['content']
        except Exception as e:
            print(f"[Evaluator LLM] Error calling OpenRouter: {e}. Falling back to Ollama...")
            return self._fallback_ollama(prompt)

    async def a_generate(self, prompt: str, schema: BaseModel = None) -> str:
        return self.generate(prompt, schema)

    def _fallback_ollama(self, prompt: str) -> str:
        import ollama
        try:
            client = ollama.Client()
            response = client.chat(
                model="mistral",
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.0}
            )
            return response['message']['content']
        except Exception as e:
            print(f"[Evaluator LLM Fallback Error] {e}")
            return "Failed to evaluate due to offline model connection."

# ==========================================
# 2. SQLITE DATABASE LOOKUP FOR RAG FILES
# ==========================================
def lookup_file_id_in_db(filename: str):
    """Retrieves the file ID from SQLite database based on filename."""
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Database not found at {DB_PATH}. Run RAG server or verify uploads first.")
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, status FROM files WHERE filename = ?", (filename,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    return {"id": row[0], "status": row[1]}

# ==========================================
# 3. RAG RUNNER PIPELINE PIPELINES
# ==========================================
def execute_rag_pipeline(file_id: str, query: str):
    """Programmatically queries the RAG backend, retrieving context and generating an answer."""
    # 1. Fetch file chunks from database
    db_chunks = get_file_chunks(file_id)
    if not db_chunks:
        raise ValueError(f"No indexed chunks found in database for file ID: {file_id}")
        
    # 2. Retrieve matched & reranked context chunks
    retrieved_chunks = RAGPipeline.retrieve(
        file_id=file_id,
        db_chunks=db_chunks,
        query=query,
        top_k=15,
        top_p=5
    )
    
    # 3. Construct contextual prompt
    prompt = RAGPipeline.construct_prompt(query, retrieved_chunks)
    
    # 4. Generate response using OpenRouter if key is present, otherwise local Ollama
    provider = "openrouter" if os.getenv("OPENROUTER_API_KEY") else "ollama"
    
    generated_text = ""
    for token in RAGPipeline.ask_ollama_stream(prompt, provider=provider):
        generated_text += token
        
    # Format retrieved contexts list for DeepEval
    contexts = [c["content"] for c in retrieved_chunks]
    
    return {
        "actual_output": generated_text.strip(),
        "retrieved_contexts": contexts
    }

# ==========================================
# 4. EVALUATION PIPELINE MAIN FUNCTION
# ==========================================
def main():
    parser = argparse.ArgumentParser(description="Confident AI DeepEval RAG Evaluation Runner")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of test queries evaluated for quick runs")
    parser.add_argument("--judge-model", type=str, default="openai/gpt-4o-mini", help="Model name on OpenRouter for DeepEval Judge")
    args = parser.parse_args()

    # Create output directory
    output_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(output_dir, exist_ok=True)

    print("\n" + "="*60)
    print("      DEEPEVAL RAG AUTOMATED PIPELINE RUNNER      ")
    print("="*60)

    # 1. Load test dataset
    dataset_path = os.path.join(output_dir, "test_dataset.json")
    if not os.path.exists(dataset_path):
        print(f"Error: Dataset not found at {dataset_path}")
        sys.exit(1)
        
    with open(dataset_path, "r", encoding="utf-8") as f:
        full_dataset = json.load(f)
        
    limit = args.limit
    test_cases = full_dataset[:limit] if limit else full_dataset
    print(f"Loaded {len(full_dataset)} total test cases from test_dataset.json.")
    if limit:
        print(f"Running in QUICK SMOKE TEST MODE: Limited to top {limit} test cases.")
    else:
        print("Running in FULL EVALUATION MODE: Processing all 30 test cases.")
    
    # 2. Check Database connectivity and resolve file IDs
    print("\n--- Resolving File IDs from Database ---")
    resolved_cases = []
    missing_files = set()
    
    for case in test_cases:
        fname = case["file_name"]
        res = lookup_file_id_in_db(fname)
        if not res:
            missing_files.add(fname)
            continue
        if res["status"] != "ready":
            print(f"Warning: File '{fname}' is in state '{res['status']}' (not ready). Skiping...")
            continue
            
        case["file_id"] = res["id"]
        resolved_cases.append(case)
        
    if missing_files:
        print(f"ERROR: The following required files are not found or indexed in the database: {list(missing_files)}")
        print("Please upload and index these documents in the UI first before running the evaluations.")
        sys.exit(1)
        
    print(f"Resolved {len(resolved_cases)} test cases against active database. Starting evaluations...\n")

    # 3. Import DeepEval metrics & instantiate judge model
    print("--- Initializing DeepEval Metrics & Judge LLM ---")
    from deepeval.metrics import (
        AnswerRelevancyMetric,
        FaithfulnessMetric,
        ContextualRelevancyMetric,
        ContextualPrecisionMetric,
        ContextualRecallMetric,
        HallucinationMetric
    )
    from deepeval.test_case import LLMTestCase

    judge_llm = OpenRouterLLM(model_name=args.judge_model)
    print(f"Judge LLM initialized using OpenRouter model: '{args.judge_model}'")

    # Instantiate 6 metrics
    ans_relevancy_metric = AnswerRelevancyMetric(threshold=0.5, model=judge_llm)
    faithfulness_metric = FaithfulnessMetric(threshold=0.5, model=judge_llm)
    ctx_relevancy_metric = ContextualRelevancyMetric(threshold=0.5, model=judge_llm)
    ctx_precision_metric = ContextualPrecisionMetric(threshold=0.5, model=judge_llm)
    ctx_recall_metric = ContextualRecallMetric(threshold=0.5, model=judge_llm)
    hallucination_metric = HallucinationMetric(threshold=0.5, model=judge_llm)

    # Dictionary to accumulate evaluation results
    results = []
    
    # Let's count success metrics
    metrics_sums = {
        "answer_relevancy": 0.0,
        "faithfulness": 0.0,
        "contextual_relevancy": 0.0,
        "contextual_precision": 0.0,
        "contextual_recall": 0.0,
        "hallucination": 0.0  # note: for hallucination, a lower score is better, or DeepEval maps it so 0 means no hallucination. In DeepEval 1 = hallucinated, so we map inverse or standard score.
    }
    
    evaluated_count = 0

    # 4. Loop and run evaluation
    for idx, case in enumerate(resolved_cases):
        print(f"\n[{idx+1}/{len(resolved_cases)}] Evaluating Query: \"{case['query']}\"")
        print(f"    Target Document: {case['file_name']}")
        
        try:
            # A. Execute programmatically
            print("    -> Querying RAG system...")
            rag_output = execute_rag_pipeline(case["file_id"], case["query"])
            actual_output = rag_output["actual_output"]
            retrieved_contexts = rag_output["retrieved_contexts"]
            
            print(f"    -> RAG generated response ({len(actual_output)} chars). Retrieved {len(retrieved_contexts)} chunks.")
            
            # B. Scaffolding LLMTestCase
            test_case = LLMTestCase(
                input=case["query"],
                actual_output=actual_output,
                expected_output=case["expected_output"],
                retrieval_context=retrieved_contexts,
                context=[case["expected_output"]]
            )
            
            # C. Evaluate each metric
            print("    -> Running DeepEval metric algorithms (Answer Relevancy & Faithfulness)...")
            ans_relevancy_metric.measure(test_case)
            ans_rel_score = ans_relevancy_metric.score
            
            faithfulness_metric.measure(test_case)
            faithfulness_score = faithfulness_metric.score
            
            print("    -> Running DeepEval metric algorithms (Contextual Relevancy & Contextual Precision)...")
            ctx_relevancy_metric.measure(test_case)
            ctx_rel_score = ctx_relevancy_metric.score
            
            ctx_precision_metric.measure(test_case)
            ctx_prec_score = ctx_precision_metric.score
            
            print("    -> Running DeepEval metric algorithms (Contextual Recall & Hallucination)...")
            ctx_recall_metric.measure(test_case)
            ctx_rec_score = ctx_recall_metric.score
            
            hallucination_metric.measure(test_case)
            hallucination_score = hallucination_metric.score # Note: In DeepEval, Hallucination score = 0 means clean, 1 means hallucinated. So we calculate 1 - hallucination_score as the grounding score.
            grounded_score = 1.0 - hallucination_score

            print(f"    -> Scores: Rel={ans_rel_score:.2f}, Faith={faithfulness_score:.2f}, CtxRel={ctx_rel_score:.2f}, CtxPrec={ctx_prec_score:.2f}, CtxRec={ctx_rec_score:.2f}, Grounded={grounded_score:.2f}")
            
            # Add to sums
            metrics_sums["answer_relevancy"] += ans_rel_score
            metrics_sums["faithfulness"] += faithfulness_score
            metrics_sums["contextual_relevancy"] += ctx_rel_score
            metrics_sums["contextual_precision"] += ctx_prec_score
            metrics_sums["contextual_recall"] += ctx_rec_score
            metrics_sums["hallucination"] += hallucination_score
            
            evaluated_count += 1
            
            # Store detail
            results.append({
                "index": idx + 1,
                "query": case["query"],
                "file_name": case["file_name"],
                "generated_answer": actual_output,
                "expected_answer": case["expected_output"],
                "answer_relevancy": ans_rel_score,
                "faithfulness": faithfulness_score,
                "contextual_relevancy": ctx_rel_score,
                "contextual_precision": ctx_prec_score,
                "contextual_recall": ctx_rec_score,
                "hallucination": hallucination_score,
                "grounded_score": grounded_score
            })
            
            # Rate limiting / stability delay
            time.sleep(2)
            
        except Exception as case_err:
            print(f"    [Error Evaluating Query {idx+1}] {case_err}")
            
    if evaluated_count == 0:
        print("No queries were successfully evaluated.")
        return

    # 5. Calculate Averages
    averages = {k: v / evaluated_count for k, v in metrics_sums.items()}
    averages["grounded_score"] = 1.0 - averages["hallucination"]

    # 6. Save Reports (JSON & CSV)
    report_json_path = os.path.join(output_dir, "report.json")
    report_csv_path = os.path.join(output_dir, "report.csv")
    
    report_payload = {
        "eval_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "evaluated_count": evaluated_count,
        "averages": averages,
        "results": results
    }
    
    with open(report_json_path, "w", encoding="utf-8") as jf:
        json.dump(report_payload, jf, indent=2)
        
    with open(report_csv_path, "w", newline="", encoding="utf-8") as cf:
        writer = csv.writer(cf)
        # Header
        writer.writerow([
            "Index", "Query", "File Name", "Answer Relevancy", "Faithfulness", 
            "Contextual Relevancy", "Contextual Precision", "Contextual Recall", "Hallucination Score", "Grounded Score"
        ])
        for r in results:
            writer.writerow([
                r["index"], r["query"], r["file_name"], r["answer_relevancy"], r["faithfulness"],
                r["contextual_relevancy"], r["contextual_precision"], r["contextual_recall"], r["hallucination"], r["grounded_score"]
            ])
            
    print(f"\n--- Saved Reports to: ---")
    print(f"  📄 JSON Report: {report_json_path}")
    print(f"  📄 CSV Report: {report_csv_path}")

    # ==========================================
    # 5. GENERATE METRIC GRAPHS (MATPLOTLIB)
    # ==========================================
    chart_path = os.path.join(output_dir, "metrics_comparison.png")
    try:
        sns.set_theme(style="darkgrid")
        plt.figure(figsize=(10, 6))
        
        metrics_names = [
            "Answer Relevancy", "Faithfulness", "Contextual Relevancy", 
            "Contextual Precision", "Contextual Recall", "Groundedness (1-Hallucination)"
        ]
        metrics_values = [
            averages["answer_relevancy"], averages["faithfulness"], averages["contextual_relevancy"],
            averages["contextual_precision"], averages["contextual_recall"], averages["grounded_score"]
        ]
        
        # Color palette
        colors = ["#4f46e5", "#10b981", "#3b82f6", "#8b5cf6", "#ec4899", "#f59e0b"]
        
        bars = plt.bar(metrics_names, metrics_values, color=colors, width=0.6, edgecolor="black", linewidth=0.7)
        plt.ylim(0, 1.1)
        plt.title("RAG System Evaluation Performance (DeepEval Metrics)", fontsize=14, fontweight="bold", pad=15)
        plt.ylabel("Score (0.0 to 1.0)", fontsize=12, labelpad=10)
        plt.xticks(rotation=15, fontsize=10, fontweight="medium")
        
        # Add labels on top of bars
        for bar in bars:
            height = bar.get_height()
            plt.annotate(f"{height:.2f}",
                         xy=(bar.get_x() + bar.get_width() / 2, height),
                         xytext=(0, 3),  # 3 points vertical offset
                         textcoords="offset points",
                         ha='center', va='bottom', fontsize=10, fontweight="bold")
                         
        plt.tight_layout()
        plt.savefig(chart_path, dpi=300)
        plt.close()
        print(f"  📊 Performance Bar Chart Saved: {chart_path}")
    except Exception as chart_err:
        print(f"  [Warning: Chart Generation failed] {chart_err}")

    # ==========================================
    # 6. CONSOLE METRIC COMPARISON SUMMARY
    # ==========================================
    print("\n" + "="*70)
    print("                 FINAL EVALUATION SUMMARY REPORT                 ")
    print("="*70)
    print(f"{'Metric Name':<35} | {'Average Score':<15} | {'Pass/Fail (Threshold=0.5)':<25}")
    print("-"*70)
    
    for key, name in [
        ("answer_relevancy", "Answer Relevancy"),
        ("faithfulness", "Faithfulness"),
        ("contextual_relevancy", "Contextual Relevancy"),
        ("contextual_precision", "Contextual Precision"),
        ("contextual_recall", "Contextual Recall")
    ]:
        score = averages[key]
        status = "✅ PASS" if score >= 0.5 else "❌ FAIL"
        print(f"{name:<35} | {score:<15.4f} | {status:<25}")
        
    g_score = averages["grounded_score"]
    g_status = "✅ PASS (Grounded)" if g_score >= 0.5 else "❌ FAIL (Hallucinated)"
    print(f"{'Groundedness (1-Hallucination)':<35} | {g_score:<15.4f} | {g_status:<25}")
    print("="*70)
    
    # Calculate overall RAG Score
    overall_score = (averages["answer_relevancy"] + averages["faithfulness"] + averages["contextual_relevancy"] +
                     averages["contextual_precision"] + averages["contextual_recall"] + averages["grounded_score"]) / 6.0
                     
    overall_status = "🏆 PREMIUM RAG WORKSPACE" if overall_score >= 0.8 else "✅ STABLE" if overall_score >= 0.5 else "⚠️ NEEDS TUNING"
    print(f"  Overall RAG Index Score: {overall_score:.4f} ({overall_status})")
    print("="*70 + "\n")

if __name__ == "__main__":
    main()
