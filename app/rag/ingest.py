from langchain_community.document_loaders import PyPDFLoader

from langchain_text_splitters import RecursiveCharacterTextSplitter

from langchain_community.vectorstores import FAISS

from langchain_openai import OpenAIEmbeddings

from langchain_huggingface import HuggingFaceEmbeddings


loader = PyPDFLoader("doc/hotel_rag_document_v2.pdf")

documents = loader.load()


text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=100
)

chunks = text_splitter.split_documents(documents)


# embeddings = OpenAIEmbeddings()
embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

vectorstore = FAISS.from_documents(
    chunks,
    embeddings
)


vectorstore.save_local("faiss_index")

print("FAISS index created successfully")

# Clear RAG cache so stale answers don't persist after knowledge base update
from app.cache.store import rag_cache
rag_cache.clear()
print("RAG cache cleared")