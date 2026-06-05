import re
import os
import csv
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
import time

def parse_logs_and_generate(log_path, output_dir):
    print(f"Parsing logs from {log_path}...")
    
    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    results = []
    # Match lines like: "    -> Scores: Rel=0.86, Faith=0.86, CtxRel=0.10, CtxPrec=1.00, CtxRec=1.00, Grounded=1.00"
    pattern = re.compile(r"Scores: Rel=([\d.]+), Faith=([\d.]+), CtxRel=([\d.]+), CtxPrec=([\d.]+), CtxRec=([\d.]+), Grounded=([\d.]+)")
    
    for line in lines:
        match = pattern.search(line)
        if match:
            results.append({
                "answer_relevancy": float(match.group(1)),
                "faithfulness": float(match.group(2)),
                "contextual_relevancy": float(match.group(3)),
                "contextual_precision": float(match.group(4)),
                "contextual_recall": float(match.group(5)),
                "grounded_score": float(match.group(6))
            })
            
    evaluated_count = len(results)
    if evaluated_count == 0:
        print("No valid scores found in the log!")
        return
        
    print(f"Successfully extracted {evaluated_count} evaluated queries!")
    
    metrics_sums = {
        "answer_relevancy": sum(r["answer_relevancy"] for r in results),
        "faithfulness": sum(r["faithfulness"] for r in results),
        "contextual_relevancy": sum(r["contextual_relevancy"] for r in results),
        "contextual_precision": sum(r["contextual_precision"] for r in results),
        "contextual_recall": sum(r["contextual_recall"] for r in results),
        "grounded_score": sum(r["grounded_score"] for r in results),
    }
    
    averages = {k: v / evaluated_count for k, v in metrics_sums.items()}
    averages["hallucination"] = 1.0 - averages["grounded_score"]
    
    os.makedirs(output_dir, exist_ok=True)
    
    # Save CSV
    report_csv_path = os.path.join(output_dir, "report.csv")
    with open(report_csv_path, "w", newline="", encoding="utf-8") as cf:
        writer = csv.writer(cf)
        writer.writerow(["Index", "Answer Relevancy", "Faithfulness", "Contextual Relevancy", "Contextual Precision", "Contextual Recall", "Grounded Score"])
        for i, r in enumerate(results):
            writer.writerow([i+1, r["answer_relevancy"], r["faithfulness"], r["contextual_relevancy"], r["contextual_precision"], r["contextual_recall"], r["grounded_score"]])
            
    # Save JSON
    report_json_path = os.path.join(output_dir, "report.json")
    report_payload = {
        "eval_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "evaluated_count": evaluated_count,
        "averages": averages
    }
    with open(report_json_path, "w", encoding="utf-8") as jf:
        json.dump(report_payload, jf, indent=2)
        
    # Generate Graph
    chart_path = os.path.join(output_dir, "metrics_comparison.png")
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
    print(f"Generated CSV: {report_csv_path}")
    print(f"Generated JSON: {report_json_path}")
    
if __name__ == "__main__":
    # Path to the task log file we just killed
    log_file = "/Users/anushka/.gemini/antigravity/brain/f4d56dfc-f0d1-4d5c-948f-fc8224053d12/.system_generated/tasks/task-2638.log"
    parse_logs_and_generate(log_file, "evaluation")
