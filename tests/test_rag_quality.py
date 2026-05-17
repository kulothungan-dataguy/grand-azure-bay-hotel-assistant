from fastapi.testclient import TestClient
from app.api.server import app
from app.rag.retriever import retriever
from ragas import evaluate, EvaluationDataset, SingleTurnSample
from ragas.metrics import Faithfulness, AnswerRelevancy, ContextRecall
from langchain_openai import OpenAIEmbeddings as LCOpenAIEmbeddings

client = TestClient(app)

# Ground truth Q&A pairs sourced directly from the hotel PDF
test_cases = [
    {
        "question": "What is the check-in time?",
        "ground_truth": "Check-in time is 2:00 PM."
    },
    {
        "question": "What is the signature dish of the hotel?",
        "ground_truth": "The Azure Spiced Seafood Platter is the signature dish, featuring fresh seafood with regional spices."
    },
    {
        "question": "What is the cancellation policy?",
        "ground_truth": "Reservations can be cancelled or modified up to 24 hours before check-in for a full refund. Late cancellations may incur charges."
    },
    {
        "question": "How does the hotel ensure hygiene?",
        "ground_truth": "Rooms are deep-cleaned after every checkout using hospital-grade disinfectants. High-touch areas such as door handles, elevators, and reception counters are sanitized multiple times a day."
    },
    {
        "question": "Is vegetarian food available?",
        "ground_truth": "The hotel accommodates dietary restrictions and provides detailed menu information including vegetarian options."
    },
    {
        "question": "How far is the hotel from the airport?",
        "ground_truth": "The hotel is located approximately 20 km from the international airport."
    },
    {
        "question": "What dining options are available?",
        "ground_truth": "The hotel offers fine dining restaurants, buffet services, and beachside cafes with international cuisines, local specialties, and customized meal plans."
    },
]


def _build_dataset() -> EvaluationDataset:
    samples = []
    for case in test_cases:
        res = client.post("/chat", json={
            "conversation_id": f"ragas-{case['question'][:20]}",
            "query": case["question"]
        })
        answer = res.json()["response"]
        docs = retriever.invoke(case["question"])
        contexts = [doc.page_content for doc in docs]

        samples.append(SingleTurnSample(
            user_input=case["question"],
            response=answer,
            retrieved_contexts=contexts,
            reference=case["ground_truth"]
        ))
    return EvaluationDataset(samples=samples)


def test_rag_quality():
    dataset = _build_dataset()

    lc_embeddings = LCOpenAIEmbeddings(model="text-embedding-3-small")

    result = evaluate(
        dataset,
        metrics=[
            Faithfulness(),
            AnswerRelevancy(embeddings=lc_embeddings),
            ContextRecall()
        ]
    )

    scores = result.to_pandas()
    print("\n--- RAGAS Scores per question ---")
    print(scores[["user_input", "faithfulness", "answer_relevancy", "context_recall"]].to_string())

    agg = {
        "faithfulness":     scores["faithfulness"].mean(),
        "answer_relevancy": scores["answer_relevancy"].mean(),
        "context_recall":   scores["context_recall"].mean(),
    }
    print("\n--- Aggregate ---")
    for metric, score in agg.items():
        print(f"  {metric}: {score:.2f}")

    assert agg["faithfulness"]     >= 0.7, f"Faithfulness too low: {agg['faithfulness']:.2f}"
    assert agg["answer_relevancy"] >= 0.7, f"Answer relevancy too low: {agg['answer_relevancy']:.2f}"
    assert agg["context_recall"]   >= 0.7, f"Context recall too low: {agg['context_recall']:.2f}"
