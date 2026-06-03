import re
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns

log_file = "/Users/anushka/.gemini/antigravity/brain/f4d56dfc-f0d1-4d5c-948f-fc8224053d12/.system_generated/tasks/task-2374.log"

metrics_sums = {
    "Rel": 0.0, "Faith": 0.0, "CtxRel": 0.0, 
    "CtxPrec": 0.0, "CtxRec": 0.0, "Grounded": 0.0
}
count = 0

with open(log_file, "r") as f:
    for line in f:
        match = re.search(r"-> Scores: Rel=([\d.]+), Faith=([\d.]+), CtxRel=([\d.]+), CtxPrec=([\d.]+), CtxRec=([\d.]+), Grounded=([\d.]+)", line)
        if match:
            metrics_sums["Rel"] += float(match.group(1))
            metrics_sums["Faith"] += float(match.group(2))
            metrics_sums["CtxRel"] += float(match.group(3))
            metrics_sums["CtxPrec"] += float(match.group(4))
            metrics_sums["CtxRec"] += float(match.group(5))
            metrics_sums["Grounded"] += float(match.group(6))
            count += 1

if count == 0:
    print("No scores found yet!")
else:
    averages = {k: v / count for k, v in metrics_sums.items()}
    
    chart_path = "evaluation/metrics_comparison.png"
    sns.set_theme(style="darkgrid")
    plt.figure(figsize=(10, 6))
    
    metrics_names = [
        "Answer Relevancy", "Faithfulness", "Contextual Relevancy", 
        "Contextual Precision", "Contextual Recall", "Groundedness"
    ]
    metrics_values = [
        averages["Rel"], averages["Faith"], averages["CtxRel"],
        averages["CtxPrec"], averages["CtxRec"], averages["Grounded"]
    ]
    
    colors = ["#4f46e5", "#10b981", "#3b82f6", "#8b5cf6", "#ec4899", "#f59e0b"]
    
    bars = plt.bar(metrics_names, metrics_values, color=colors, width=0.6, edgecolor="black", linewidth=0.7)
    plt.ylim(0, 1.1)
    plt.title(f"RAG System Evaluation Performance ({count} Queries Processed Live)", fontsize=14, fontweight="bold", pad=15)
    plt.ylabel("Score (0.0 to 1.0)", fontsize=12, labelpad=10)
    plt.xticks(rotation=15, fontsize=10, fontweight="medium")
    
    for bar in bars:
        height = bar.get_height()
        plt.annotate(f"{height:.2f}",
                     xy=(bar.get_x() + bar.get_width() / 2, height),
                     xytext=(0, 3),
                     textcoords="offset points",
                     ha='center', va='bottom', fontsize=10, fontweight="bold")
                     
    plt.tight_layout()
    plt.savefig(chart_path, dpi=300)
    plt.close()
    print(f"Successfully generated live graph for {count} queries!")
