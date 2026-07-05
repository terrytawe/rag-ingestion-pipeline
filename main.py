from langchain_ollama.embeddings import OllamaEmbeddings
from langchain_anthropic import ChatAnthropic
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_chroma import Chroma
from pathlib import Path
from dotenv import load_dotenv

from config import (
    CHROMA_DIR,
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    RETRIEVAL_SEARCH_TYPE,
    RETRIEVAL_K,
    RETRIEVAL_FETCH_K,
    RETRIEVAL_LAMBDA_MULT,
)

load_dotenv()

embeddings_model = OllamaEmbeddings(model=EMBEDDING_MODEL)


def get_vector_store() -> Chroma:
    """
    Open the persisted store that ingest.py writes to.
    This does not create or populate anything. If chroma_db does not
    exist yet, run ingest.py first.
    """
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings_model,
        persist_directory=str(CHROMA_DIR),
    )


def format_docs(docs):
    formatted = []
    for idx, doc in enumerate(docs, start=1):
        source = doc.metadata.get("source_path", "unknown")
        page = doc.metadata.get("page")
        modality = doc.metadata.get("modality", "text")

        page_display = "n/a"
        if isinstance(page, int):
            page_display = str(page + 1)

        formatted.append(
            f"[{idx}] source={source}; page={page_display}; modality={modality}\n{doc.page_content}"
        )

    return "\n\n".join(formatted)


def build_rag_chain():
    """
    Build the retrieval and generation chain.
    Kept separate from any input mechanism on purpose. When a UI replaces
    the CLI loop below, it should import build_rag_chain() and call
    .invoke(question) directly, it should not need to know this module
    ever had a command line interface at all.
    """
    vector_store = get_vector_store()
    retriever = vector_store.as_retriever(
        search_type=RETRIEVAL_SEARCH_TYPE,
        search_kwargs={
            "k": RETRIEVAL_K,
            "fetch_k": RETRIEVAL_FETCH_K,
            "lambda_mult": RETRIEVAL_LAMBDA_MULT,
        },
    )

    # llm = ChatAnthropic(model_name="claude-sonnet-5")
    llm = ChatOllama(model="qwen3.6:27b-mlx-bf16") # Vram issues on current machine

    answer_template = Path("prompts/answer.txt").read_text()
    prompt = ChatPromptTemplate.from_template(answer_template)

    return (
        {"context": retriever | format_docs, "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )


def run_cli():
    """
    Command line loop for local testing.
    This is the piece that gets deleted, not adapted, when the UI arrives.
    The UI will call build_rag_chain().invoke(question) on its own.
    """
    rag_chain = build_rag_chain()

    print("RAG query loop. Type a question, or 'exit' to quit.\n")
    while True:
        question = input("Q: ").strip()
        if question.lower() in {"exit", "quit"}:
            break
        if not question:
            continue
        answer = rag_chain.invoke(question)
        print(f"A: {answer}\n")


if __name__ == "__main__":
    run_cli()