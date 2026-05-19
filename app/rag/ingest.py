import re
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings


# ---------------------------------------------------------------------------
# Heading-aware section splitter
# ---------------------------------------------------------------------------

# A heading line is:
#   - 4–60 characters long
#   - Starts with a capital letter
#   - At most 8 words (body text wraps to longer lines)
#   - Does not end with sentence-terminating punctuation
_HEADING_RE = re.compile(r'^[A-Z][^\n]{3,59}$')
_TERMINAL_PUNCT = ('.', ',', ';', '!', '?')


def _is_heading(line: str) -> bool:
    if not _HEADING_RE.match(line):
        return False
    if line.endswith(_TERMINAL_PUNCT):
        return False
    if len(line.split()) > 8:
        return False
    return True


def _parse_sections(pages: list) -> list[Document]:
    """
    Split the hotel PDF into semantic sections.
    Each section becomes one Document:
      page_content = "<Heading>\n\n<body text>"
      metadata     = {"section": "<Heading>", "page": <0-indexed page number>}
    """
    sections: list[Document] = []
    current_section = "Introduction"
    current_lines: list[str] = []
    current_page = 0

    for page_num, page_doc in enumerate(pages):
        for line in page_doc.page_content.split('\n'):
            line = line.strip()
            if not line:
                continue

            if _is_heading(line):
                # Flush accumulated body text as a completed section
                if current_lines:
                    body = " ".join(current_lines)
                    sections.append(Document(
                        page_content=f"{current_section}\n\n{body}",
                        metadata={"section": current_section, "page": current_page},
                    ))
                    current_lines = []
                current_section = line
                current_page = page_num
            else:
                current_lines.append(line)

    # Flush the final section
    if current_lines:
        body = " ".join(current_lines)
        sections.append(Document(
            page_content=f"{current_section}\n\n{body}",
            metadata={"section": current_section, "page": current_page},
        ))

    return sections


# ---------------------------------------------------------------------------
# Build FAISS index
# ---------------------------------------------------------------------------

loader = PyPDFLoader("doc/hotel_rag_document_v2.pdf")
pages = loader.load()

sections = _parse_sections(pages)

print(f"Sections found: {len(sections)}")
for s in sections:
    print(f"  [{s.metadata['page']+1}] {s.metadata['section']!r}  ({len(s.page_content)} chars)")

embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

vectorstore = FAISS.from_documents(sections, embeddings)
vectorstore.save_local("faiss_index")
print("\nFAISS index rebuilt successfully")

# Clear RAG cache so stale answers don't persist after knowledge base update
from app.cache.store import rag_cache
rag_cache.clear()
print("RAG cache cleared")
