import os
import sys
import json
import csv
import time
os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] = "YES"
import argparse
import requests
import matplotlib
from dotenv import load_dotenv
load_dotenv()
# Force local Ollama by removing API key from environment
if "OPENROUTER_API_KEY" in os.environ:
    del os.environ["OPENROUTER_API_KEY"]
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.pipeline import execute_rag_pipeline
from pydantic import BaseModel

try:
    from deepeval.metrics import (
        AnswerRelevancyMetric,
        FaithfulnessMetric,
        ContextualRelevancyMetric,
        ContextualPrecisionMetric,
        ContextualRecallMetric,
        HallucinationMetric
    )
    from deepeval.test_case import LLMTestCase
    from deepeval.models.base_model import DeepEvalBaseLLM
except ImportError:
    print("DeepEval is not installed. Please run: pip install deepeval")
    sys.exit(1)

def clean_json_output(text: str) -> str:
    """Removes markdown code blocks if the LLM wrapped the JSON."""
    if not text:
        return "{}"
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    first_brace = text.find('{')
    last_brace = text.rfind('}')
    if first_brace != -1 and last_brace != -1:
        return text[first_brace:last_brace+1]
    return text

class OllamaLLM(DeepEvalBaseLLM):
    def __init__(self, model_name="mistral"):
        self.model_name = model_name

    def get_model_name(self):
        return self.model_name

    def load_model(self):
        return self

    def generate(self, prompt: str, schema: BaseModel = None) -> str:
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.0}
        }
        
        if schema:
            payload["format"] = "json"
            
        max_retries = 3
        for attempt in range(max_retries):
            print(f"[Evaluator] Requesting local {self.model_name}...")
            try:
                response = requests.post(
                    "http://localhost:11434/api/chat",
                    json=payload,
                    timeout=120
                )
                if response.status_code != 200:
                    print(f"[Evaluator] Error {response.status_code}. Retrying...")
                    time.sleep(2)
                    continue
                
                res_json = response.json()
                content = res_json.get('message', {}).get('content', '')
                cleaned = clean_json_output(content) if schema else content
                return cleaned
            except Exception as e:
                print(f"[Evaluator] Request failed: {e}. Retrying...")
                time.sleep(2)
        
        return "{}"

    async def a_generate(self, prompt: str, schema: BaseModel = None) -> str:
        return self.generate(prompt, schema)


def main():
    parser = argparse.ArgumentParser(description="DeepEval RAG Evaluator")
    parser.add_argument("--judge-model", type=str, default="mistral", help="Ollama model name")
    parser.add_argument("--top-k", type=int, default=3, help="Number of chunks to retrieve during RAG")
    args = parser.parse_args()

    dataset_path = "evaluation/test_dataset.json"
    output_dir = "evaluation"
    os.makedirs(output_dir, exist_ok=True)
    
    if not os.path.exists(dataset_path):
        print(f"Dataset {dataset_path} not found. Run generate_dataset.py first.")
        return
        
    with open(dataset_path, "r", encoding="utf-8") as f:
        cases = json.load(f)
        
    if not cases:
        print("Dataset is empty.")
        return

    print("="*60)
    print("      DEEPEVAL RAG AUTOMATED PIPELINE RUNNER      ")
    print("="*60)
    print(f"Loaded {len(cases)} test cases.")

    judge_llm = OllamaLLM(model_name=args.judge_model)
    print(f"Judge LLM initialized using local Ollama: '{args.judge_model}'")
    
    # Instantiate 6 metrics
    ans_relevancy_metric = AnswerRelevancyMetric(threshold=0.5, model=judge_llm)
    faithfulness_metric = FaithfulnessMetric(threshold=0.5, model=judge_llm)
    ctx_relevancy_metric = ContextualRelevancyMetric(threshold=0.5, model=judge_llm)
    ctx_precision_metric = ContextualPrecisionMetric(threshold=0.5, model=judge_llm)
    ctx_recall_metric = ContextualRecallMetric(threshold=0.5, model=judge_llm)
    hallucination_metric = HallucinationMetric(threshold=0.5, model=judge_llm)
    
    results = []
    metrics_sums = {
        "answer_relevancy": 0.0,
        "faithfulness": 0.0,
        "contextual_relevancy": 0.0,
        "contextual_precision": 0.0,
        "contextual_recall": 0.0,
        "hallucination": 0.0
    }
    
    evaluated_count = 0

    for idx, case in enumerate(cases):
        print(f"\n[{idx+1}/{len(cases)}] Query: \"{case['query']}\"")
        
        try:
            print("    -> Querying RAG system...")
            rag_output = execute_rag_pipeline(case["file_id"], case["query"], top_p=args.top_k)
            actual_output = rag_output["actual_output"]
            retrieved_contexts = rag_output["retrieved_contexts"]
            
            # Construct DeepEval LLMTestCase
            test_case = LLMTestCase(
                input=case["query"],
                actual_output=actual_output,
                expected_output=case["expected_output"],
                retrieval_context=retrieved_contexts,
                context=[case["expected_output"]]
            )
            
            # Evaluate metrics
            print("    -> Running DeepEval metrics...")
            ans_relevancy_metric.measure(test_case)
            faithfulness_metric.measure(test_case)
            ctx_relevancy_metric.measure(test_case)
            ctx_precision_metric.measure(test_case)
            ctx_recall_metric.measure(test_case)
            hallucination_metric.measure(test_case)
            
            a_rel = ans_relevancy_metric.score
            f_score = faithfulness_metric.score
            c_rel = ctx_relevancy_metric.score
            c_prec = ctx_precision_metric.score
            c_rec = ctx_recall_metric.score
            h_score = hallucination_metric.score
            g_score = 1.0 - h_score # Groundedness
            
            print(f"    -> Scores: Rel={a_rel:.2f}, Faith={f_score:.2f}, CtxRel={c_rel:.2f}, CtxPrec={c_prec:.2f}, CtxRec={c_rec:.2f}, Grounded={g_score:.2f}")
            
            metrics_sums["answer_relevancy"] += a_rel
            metrics_sums["faithfulness"] += f_score
            metrics_sums["contextual_relevancy"] += c_rel
            metrics_sums["contextual_precision"] += c_prec
            metrics_sums["contextual_recall"] += c_rec
            metrics_sums["hallucination"] += h_score
            
            evaluated_count += 1
            
            results.append({
                "index": idx + 1,
                "query": case["query"],
                "file_name": case["file_name"],
                "generated_answer": actual_output,
                "expected_answer": case["expected_output"],
                "answer_relevancy": a_rel,
                "faithfulness": f_score,
                "contextual_relevancy": c_rel,
                "contextual_precision": c_prec,
                "contextual_recall": c_rec,
                "hallucination": h_score,
                "grounded_score": g_score
            })
            
        except Exception as case_err:
            print(f"    [Error] {case_err}")
            
    if evaluated_count == 0:
        print("No queries were successfully evaluated.")
        return

    # Averages
    averages = {k: v / evaluated_count for k, v in metrics_sums.items()}
    averages["grounded_score"] = 1.0 - averages["hallucination"]

    # Save JSON and CSV
    report_json_path = os.path.join(output_dir, "report_ollama.json")
    report_csv_path = os.path.join(output_dir, "report_ollama.csv")
    qa_metrics_path = os.path.join(output_dir, "qa_comparison_with_metrics_ollama.md")
    
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
        writer.writerow(["Index", "Query", "File Name", "Answer Relevancy", "Faithfulness", "Contextual Relevancy", "Contextual Precision", "Contextual Recall", "Hallucination Score", "Grounded Score"])
        for r in results:
            writer.writerow([r["index"], r["query"], r["file_name"], r["answer_relevancy"], r["faithfulness"], r["contextual_relevancy"], r["contextual_precision"], r["contextual_recall"], r["hallucination"], r["grounded_score"]])
            
    with open(qa_metrics_path, "w", encoding="utf-8") as mf:
        mf.write("# RAG Evaluation Results (Local Ollama)\n\n")
        mf.write("This document compares the expected answers from the dataset against the answers generated by the local Ollama model via the RAG pipeline, along with DeepEval metrics.\n\n")
        for r in results:
            mf.write(f"## Question {r['index']}\n")
            mf.write(f"**Query:** {r['query']}\n\n")
            mf.write("### Expected Answer\n")
            mf.write(f"> {r['expected_answer']}\n\n")
            mf.write("### RAG Generated Answer (OpenRouter)\n")
            mf.write(f"{r['generated_answer']}\n\n")
            mf.write("### Metrics\n")
            mf.write(f"- **Answer Relevancy:** {r['answer_relevancy']:.2f}\n")
            mf.write(f"- **Faithfulness:** {r['faithfulness']:.2f}\n")
            mf.write(f"- **Contextual Relevancy:** {r['contextual_relevancy']:.2f}\n")
            mf.write(f"- **Contextual Precision:** {r['contextual_precision']:.2f}\n")
            mf.write(f"- **Contextual Recall:** {r['contextual_recall']:.2f}\n")
            mf.write(f"- **Hallucination:** {r['hallucination']:.2f}\n")
            mf.write(f"- **Grounded Score:** {r['grounded_score']:.2f}\n")
            mf.write("---\n\n")

    print(f"\nSaved Reports to {output_dir}/")

    # Generate Graphs
    chart_path = os.path.join(output_dir, "metrics_comparison_ollama.png")
    try:
        sns.set_theme(style="darkgrid")
        plt.figure(figsize=(10, 6))
        metrics_names = ["Answer Relevancy", "Faithfulness", "Contextual Relevancy", "Contextual Precision", "Contextual Recall", "Groundedness"]
        metrics_values = [averages["answer_relevancy"], averages["faithfulness"], averages["contextual_relevancy"], averages["contextual_precision"], averages["contextual_recall"], averages["grounded_score"]]
        
        colors = ["#4f46e5", "#10b981", "#3b82f6", "#8b5cf6", "#ec4899", "#f59e0b"]
        bars = plt.bar(metrics_names, metrics_values, color=colors, width=0.6, edgecolor="black", linewidth=0.7)
        plt.ylim(0, 1.1)
        plt.title(f"RAG Evaluation Performance (Avg of {evaluated_count} Queries)", fontsize=14, fontweight="bold", pad=15)
        plt.ylabel("Score (0.0 to 1.0)", fontsize=12, labelpad=10)
        plt.xticks(rotation=15, fontsize=10, fontweight="medium")
        
        for bar in bars:
            height = bar.get_height()
            plt.annotate(f"{height:.2f}", xy=(bar.get_x() + bar.get_width() / 2, height), xytext=(0, 3), textcoords="offset points", ha='center', va='bottom', fontsize=10, fontweight="bold")
                         
        plt.tight_layout()
        plt.savefig(chart_path, dpi=300)
        plt.close()
        print(f"Generated chart: {chart_path}")
    except Exception as e:
        print(f"Chart generation failed: {e}")

    # Console Summary
    print("\n" + "="*70)
    print("                 FINAL EVALUATION SUMMARY REPORT                 ")
    print("="*70)
    for key, name in [("answer_relevancy", "Answer Relevancy"), ("faithfulness", "Faithfulness"), ("contextual_relevancy", "Contextual Relevancy"), ("contextual_precision", "Contextual Precision"), ("contextual_recall", "Contextual Recall")]:
        status = "✅ PASS" if averages[key] >= 0.5 else "❌ FAIL"
        print(f"{name:<35} | {averages[key]:<15.4f} | {status:<25}")
    g_status = "✅ PASS" if averages["grounded_score"] >= 0.5 else "❌ FAIL"
    print(f"{'Groundedness':<35} | {averages['grounded_score']:<15.4f} | {g_status:<25}")
    print("="*70 + "\n")

if __name__ == "__main__":
    main()
