import os
import json
import asyncio
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from typing import List, Dict

# Set OpenAI API key to use OpenRouter for DeepEval
from backend.app.config import OPENROUTER_API_KEY, OPENROUTER_MODEL_NAME
import pytest  # deepeval requires this for testing

from deepeval.models.base_model import DeepEvalBaseLLM
from openai import AsyncOpenAI, OpenAI


class OpenRouterLLM(DeepEvalBaseLLM):
    """Real LLM judge that calls the OpenRouter API for DeepEval metric scoring."""

    def __init__(self):
        self.model_name = OPENROUTER_MODEL_NAME
        self.async_client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_API_KEY,
        )
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_API_KEY,
        )

    def load_model(self):
        return self.client

    def generate(self, prompt: str) -> str:
        """Calls the real OpenRouter API to get a judgment from the LLM judge."""
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content

    async def a_generate(self, prompt: str) -> str:
        """Async version — calls the real OpenRouter API."""
        response = await self.async_client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content

    def get_model_name(self):
        return self.model_name


# Import DeepEval components
from deepeval.test_case import LLMTestCase
from deepeval.metrics import (
    AnswerRelevancyMetric,
    FaithfulnessMetric,
    ContextualRelevancyMetric,
    ContextualPrecisionMetric,
    ContextualRecallMetric,
    HallucinationMetric,
)
from deepeval.evaluate import evaluate

# Import RAG pipeline
from backend.app.pipeline import RAGPipeline
from backend.app.storage import get_file_chunks

FILE_IDS = [
    "450a1c31-d431-4398-86f1-5cfb7e4650ee",
    "2ff1cbd9-c724-4c2d-9f13-c4e0c72b27ea",
    "498e5194-7c2a-4909-9565-f631f8481d82",
    "2aac5378-8f84-4d35-bf1f-ff88d11eac25",
]
DATASET_PATH = os.path.join(os.path.dirname(__file__), "test_dataset.json")
REPORT_CSV_PATH = os.path.join(os.path.dirname(__file__), "report.csv")
REPORT_JSON_PATH = os.path.join(os.path.dirname(__file__), "report.json")
GRAPH_PATH = os.path.join(os.path.dirname(__file__), "metrics_comparison.png")


def get_rag_response(query: str, expected_output: str, db_chunks_map: dict) -> tuple[str, List[str]]:
    """Runs the full RAG pipeline for a given query — retrieval, reranking, and generation."""
    print(f"Retrieving for: {query}")

    all_retrieved_chunks = []
    try:
        for fid, db_chunks in db_chunks_map.items():
            if db_chunks:
                file_chunks = RAGPipeline.retrieve(
                    file_id=fid,
                    db_chunks=db_chunks,
                    query=query,
                    top_k=20,
                    top_p=8,
                    skip_reranking=True,
                )
                all_retrieved_chunks.extend(file_chunks)

        all_retrieved_chunks.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        candidates_to_rerank = all_retrieved_chunks[:60]

        from backend.app.pipeline import get_reranker_model

        reranker = get_reranker_model()
        pairs = [[query, item["content"]] for item in candidates_to_rerank]
        if pairs:
            rerank_scores = reranker.predict(pairs)
            for idx, r_score in enumerate(rerank_scores):
                candidates_to_rerank[idx]["rerank_score"] = float(r_score)

        candidates_to_rerank.sort(
            key=lambda x: x.get("rerank_score", x.get("score", 0)), reverse=True
        )
        final_chunks = candidates_to_rerank[:20]

    except Exception as e:
        print(f"Retrieval error: {e}")
        final_chunks = []

    context_list = [chunk["content"] for chunk in final_chunks]
    context_str = RAGPipeline.construct_prompt(query, final_chunks)

    generator = RAGPipeline.ask_ollama_stream(query, context_str, provider="openrouter")
    full_answer = ""
    for token in generator:
        full_answer += token

    return full_answer, context_list


def main():
    print("=== DeepEval Integration ===")

    if not os.path.exists(DATASET_PATH):
        print(f"Dataset not found at {DATASET_PATH}")
        return

    with open(DATASET_PATH, "r") as f:
        dataset = json.load(f)

    print(f"Loaded {len(dataset)} queries.")

    print("Loading DB chunks for retrieval...")
    db_chunks_map = {}
    for fid in FILE_IDS:
        db_chunks_map[fid] = get_file_chunks(fid)

    test_cases = []

    print("\n--- Running RAG Pipeline ---")
    for i, data in enumerate(dataset):
        query = data["query"]
        expected_output = data["expected_output"]

        actual_output, retrieval_context = get_rag_response(query, expected_output, db_chunks_map)

        test_case = LLMTestCase(
            input=query,
            actual_output=actual_output,
            expected_output=expected_output,
            retrieval_context=retrieval_context,
        )
        test_cases.append(test_case)
        print(f"[{i+1}/{len(dataset)}] Finished generation.")

    print("\n--- Running DeepEval Metrics ---")
    custom_model = OpenRouterLLM()

    # Initialize metrics with the real LLM judge
    metrics = [
        AnswerRelevancyMetric(threshold=0.5, model=custom_model),
        FaithfulnessMetric(threshold=0.5, model=custom_model),
        ContextualRelevancyMetric(threshold=0.5, model=custom_model),
        ContextualPrecisionMetric(threshold=0.5, model=custom_model),
        ContextualRecallMetric(threshold=0.5, model=custom_model),
        HallucinationMetric(threshold=0.5, model=custom_model),
    ]

    # Run the real DeepEval evaluation
    results = evaluate(test_cases, metrics)

    print("\n--- Processing Results ---")

    report_data = []
    metric_scores = {m.__class__.__name__: [] for m in metrics}

    for idx, tc in enumerate(test_cases):
        row = {
            "query": tc.input,
            "expected_output": tc.expected_output,
            "actual_output": tc.actual_output,
            "success": all(m.success for m in metrics),
        }
        # Read real scores from each metric after evaluation
        for m in metrics:
            metric_name = m.__class__.__name__
            score = m.score if m.score is not None else 0.0
            row[metric_name] = score
            metric_scores[metric_name].append(score)

        report_data.append(row)

    # Save CSV
    df = pd.DataFrame(report_data)
    df.to_csv(REPORT_CSV_PATH, index=False)

    # Save JSON
    with open(REPORT_JSON_PATH, "w") as f:
        json.dump(df.to_dict(orient="records"), f, indent=4)

    # Generate Graph
    print("Generating visual graph...")
    avg_scores = {}
    for name, scores in metric_scores.items():
        if scores:
            avg_scores[name] = sum(scores) / len(scores)

    plt.figure(figsize=(10, 6))
    sns.barplot(x=list(avg_scores.values()), y=list(avg_scores.keys()), palette="viridis")
    plt.title("Average DeepEval RAG Metrics")
    plt.xlabel("Average Score (0.0 - 1.0)")
    plt.xlim(0, 1.0)
    plt.tight_layout()
    plt.savefig(GRAPH_PATH)
    plt.close()

    # Console Output
    print("\n=== FINAL EVALUATION REPORT ===")
    print(df.drop(columns=["actual_output", "expected_output", "query"]).mean().to_string())
    print("\nAll tasks complete! Results saved to:")
    print(f"CSV: {REPORT_CSV_PATH}")
    print(f"JSON: {REPORT_JSON_PATH}")
    print(f"Graph: {GRAPH_PATH}")


if __name__ == "__main__":
    main()
