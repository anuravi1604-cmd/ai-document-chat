import json
import csv
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns

output_dir = "evaluation"
report_json_path = os.path.join(output_dir, "report.json")

try:
    with open(report_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    averages = data["averages"]
    
    # 5. GENERATE METRIC GRAPHS (MATPLOTLIB)
    chart_path = os.path.join(output_dir, "metrics_comparison.png")
    sns.set_theme(style="darkgrid")
    plt.figure(figsize=(10, 6))
    
    metrics_names = [
        "Answer Relevancy", "Faithfulness", "Contextual Relevancy", 
        "Contextual Precision", "Contextual Recall", "Groundedness"
    ]
    metrics_values = [
        averages.get("answer_relevancy", 0), averages.get("faithfulness", 0), averages.get("contextual_relevancy", 0),
        averages.get("contextual_precision", 0), averages.get("contextual_recall", 0), averages.get("grounded_score", 0)
    ]
    
    colors = ["#4f46e5", "#10b981", "#3b82f6", "#8b5cf6", "#ec4899", "#f59e0b"]
    
    bars = plt.bar(metrics_names, metrics_values, color=colors, width=0.6, edgecolor="black", linewidth=0.7)
    plt.ylim(0, 1.1)
    plt.title(f"RAG System Evaluation Performance ({data['evaluated_count']} Queries)", fontsize=14, fontweight="bold", pad=15)
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
    print("Successfully generated metrics_comparison.png from existing report.json")
except Exception as e:
    print("Error:", e)
