from app.rag.retriever import retriever


def test_retriever_returns_docs():

    docs = retriever.invoke(
        "What is the famous dish?"
    )

    assert len(docs) > 0