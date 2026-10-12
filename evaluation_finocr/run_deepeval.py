import os
import sys

# Allow longer local Ollama judge evaluations
os.environ["DEEPEVAL_PER_TASK_TIMEOUT_SECONDS_OVERRIDE"] = "600"
os.environ["DEEPEVAL_PER_ATTEMPT_TIMEOUT_SECONDS_OVERRIDE"] = "300"
os.environ["DEEPEVAL_RETRY_MAX_ATTEMPTS"] = "2"

# Ensure workspace root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


# Prevent macOS threading conflicts and HuggingFace parallel crashes
os.environ["USE_TF"] = "0"
os.environ["USE_TORCH"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import torch
torch.set_num_threads(1)

import json
import sqlite3
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from typing import List, Dict, Any

from deepeval.models import OllamaModel
from deepeval.test_case import LLMTestCase
from deepeval.metrics import (
    AnswerRelevancyMetric,
    FaithfulnessMetric,
    ContextualRelevancyMetric,
    ContextualPrecisionMetric,
    ContextualRecallMetric,
    HallucinationMetric
)

from backend.app.config import DB_PATH
from backend.app.pipeline import RAGPipeline, get_reranker_model
from backend.app.storage import get_file_chunks

DATASET_PATH = os.path.join(os.path.dirname(__file__), "test_dataset.json")
REPORT_CSV_PATH = os.path.join(os.path.dirname(__file__), "report.csv")
REPORT_JSON_PATH = os.path.join(os.path.dirname(__file__), "report.json")
GRAPH_PATH = os.path.join(os.path.dirname(__file__), "metrics_comparison.png")

def get_active_document_file_ids() -> List[str]:
    """Retrieves document file IDs that are ready in the database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, filename, file_type FROM files WHERE status = 'ready' AND file_type IN ('pdf', 'docx', 'txt')")
    rows = c.fetchall()
    conn.close()
    
    # Pick unique filenames to avoid duplicates
    seen_names = set()
    selected_ids = []
    for fid, fname, ftype in rows:
        if fname not in seen_names:
            seen_names.add(fname)
            selected_ids.append(fid)
            
    print(f"[Init] Found {len(selected_ids)} unique ready documents: {list(seen_names)}")
    return selected_ids

def execute_rag(query: str, file_ids: List[str]) -> tuple[str, List[str]]:
    """Runs real multi-file hybrid retrieval, cross-encoder reranking, and Mistral generation."""
    all_retrieved = []
    for fid in file_ids:
        try:
            chunks = get_file_chunks(fid)
            if chunks:
                ret = RAGPipeline.retrieve(
                    file_id=fid,
                    db_chunks=chunks,
                    query=query,
                    top_k=5,
                    top_p=3,
                    skip_reranking=True
                )
                all_retrieved.extend(ret)
        except Exception as e:
            print(f"  [Warning] Retrieval error for {fid}: {e}")

    if not all_retrieved:
        return "I cannot find the answer in the provided documents.", ["No context retrieved."]

    # Global Cross-Encoder Reranking
    all_retrieved.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    candidates = all_retrieved[:25]
    reranker = get_reranker_model()
    pairs = [[query, item["content"]] for item in candidates]
    
    if pairs:
        rerank_scores = reranker.predict(pairs)
        for idx, s in enumerate(rerank_scores):
            candidates[idx]["rerank_score"] = float(s)
        candidates.sort(key=lambda x: x.get("rerank_score", 0.0), reverse=True)
        
    top_candidates = candidates[:5]
    context_list = [c["content"][:1500] for c in top_candidates]
    context_str = RAGPipeline.construct_prompt(query, top_candidates)
    
    # Generate actual answer via Ollama Mistral
    token_generator = RAGPipeline.ask_ollama_stream(query, context_str, provider="ollama")
    actual_output = "".join(list(token_generator)).strip()
    return actual_output, context_list

def main():
    print("=" * 65)
    print("=== GENUINE DEEPEVAL RAG EVALUATION (FinOCR Benchmark) ===")
    print("=" * 65)

    if not os.path.exists(DATASET_PATH):
        print(f"Dataset not found at {DATASET_PATH}")
        sys.exit(1)

    with open(DATASET_PATH, "r") as f:
        dataset = json.load(f)

    file_ids = get_active_document_file_ids()
    eval_judge_model = OllamaModel(model="mistral", base_url="http://localhost:11434")

    # Define the 6 metrics to evaluate
    metric_instances = [
        AnswerRelevancyMetric(
            threshold=0.5,
            model=eval_judge_model,
            async_mode=False
        ),
        FaithfulnessMetric(
            threshold=0.5,
            model=eval_judge_model,
            async_mode=False
        ),
        ContextualRelevancyMetric(
            threshold=0.5,
            model=eval_judge_model,
            async_mode=False
        ),
        ContextualPrecisionMetric(
            threshold=0.5,
            model=eval_judge_model,
            async_mode=False
        ),
        ContextualRecallMetric(
            threshold=0.5,
            model=eval_judge_model,
            async_mode=False
        ),
        HallucinationMetric(
            threshold=0.5,
            model=eval_judge_model,
            async_mode=False
        )
    ]


    report_records = []
    metric_scores = {m.__class__.__name__: [] for m in metric_instances}

    for idx, item in enumerate(dataset):
        query = item["query"]
        expected_output = item["expected_output"]
        print(f"\n[{idx + 1}/{len(dataset)}] Query: {query}")

        # 1. Real RAG execution
        actual_output, retrieval_context = execute_rag(query, file_ids)
        print(f"  -> Generated: {actual_output[:110]}...")

        # 2. Build test case with both retrieval_context and context
        test_case = LLMTestCase(
            input=query,
            actual_output=actual_output,
            expected_output=expected_output,
            context=retrieval_context,
            retrieval_context=retrieval_context
        )

        row = {
            "query": query,
            "expected_output": expected_output,
            "actual_output": actual_output,
            "retrieval_context": retrieval_context
        }

        # 3. Calculate each metric authentically
    
        for m in metric_instances:
            m_name = m.__class__.__name__

            try:
                m.measure(test_case)
                score = round(float(m.score), 4)
                reason = getattr(m, "reason", "") or ""

                if not 0.0 <= score <= 1.0:
                    raise ValueError(f"Invalid score: {score}")

                # Store only successful scores for calculating averages
                metric_scores[m_name].append(score)

            except Exception as e:
                print(f"    [Error] {m_name} failed: {type(e).__name__}: {e}")
                score = None
                reason = f"Evaluation failed: {type(e).__name__}: {e}"

            row[m_name] = score
            row[f"{m_name}_reason"] = reason

            if score is not None:
                print(f"    {m_name:<26}: {score:.4f}")
            else:
                print(f"    {m_name:<26}: FAILED (excluded from average)")

        report_records.append(row)

    # 4. Save CSV report
    df = pd.DataFrame(report_records)
    score_cols = [m.__class__.__name__ for m in metric_instances]
    df.to_csv(REPORT_CSV_PATH, index=False)

    # 5. Save JSON report
    with open(REPORT_JSON_PATH, "w") as f:
        json.dump(report_records, f, indent=4)

    # 6. Generate genuine visualization chart
    print("\n[Chart] Generating metrics comparison bar chart...")
    
    avg_scores = {
        name: (sum(scores) / len(scores) if scores else float("nan"))
        for name, scores in metric_scores.items()
    }
    valid_scores = {
    name: score for name, score in avg_scores.items()
    if pd.notna(score)
    }
    plt.figure(figsize=(10, 6))
    bars = sns.barplot(
        x=list(valid_scores.values()),
        y=list(valid_scores.keys()),
        palette="viridis"
    )
    plt.title("Authentic DeepEval RAG Metrics (Mistral Judge)", fontsize=14, fontweight="bold", pad=15)
    plt.xlabel("Average Score (0.0 - 1.0)", fontsize=12)
    plt.xlim(0, 1.05)

    # Annotate bars with exact numbers
    for bar in bars.patches:
        width = bar.get_width()
        y = bar.get_y() + bar.get_height() / 2
        plt.text(width + 0.02, y, f"{width:.3f}", va="center", ha="left", fontsize=10, fontweight="bold")

    plt.tight_layout()
    plt.savefig(GRAPH_PATH, dpi=300)
    plt.close()

    # 7. Print Final Summary Table
    print("\n" + "=" * 65)
    print("=== FINAL AUTHENTIC BENCHMARK SUMMARY ===")
    print("=" * 65)
    for m_name, avg in avg_scores.items():
        print(f"  {m_name:<28}: {avg:.4f}")
    print("=" * 65)
    print(f"Artifacts saved:")
    print(f"  - CSV:   {REPORT_CSV_PATH}")
    print(f"  - JSON:  {REPORT_JSON_PATH}")
    print(f"  - Chart: {GRAPH_PATH}")

if __name__ == "__main__":
    main()
