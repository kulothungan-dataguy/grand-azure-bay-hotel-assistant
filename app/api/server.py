from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from app.graph.workflow import graph
from app.graph.nodes import llm
from app.rag.retriever import retriever
from app.rag.prompts import RAG_PROMPT
from app.rag.intent_prompt import INTENT_PROMPT
from app.schemas.intent_schema import IntentOutput
from app.db.models import create_tables
from app.utils.logger import logger
from app.schemas.api_schemas import ChatRequest, ChatResponse
from app.memory.store import conversation_memory


app = FastAPI()

create_tables()


@app.post(
    "/chat",
    response_model=ChatResponse
)
def chat(
    payload: ChatRequest
):
    query = payload.query

    conversation_id = (
    payload.conversation_id
    )

    if conversation_id not in (
    conversation_memory
    ):

        conversation_memory[
            conversation_id
        ] = {

            "chat_history": [],

            "current_reservation": None
        }

    conversation_memory[conversation_id]["chat_history"].append({
    "role": "user",
    "content": query
    })

    logger.info(f"Conversation {conversation_id}: {len(conversation_memory[conversation_id]['chat_history'])} turns")

    response = graph.invoke({

        "query": query,

        "intent": None,

        "response": None,

        "reservation_data": None,

        "reservation_id": None,

        "current_reservation":
            conversation_memory[
                conversation_id
            ]["current_reservation"],

        "chat_history":
            conversation_memory[
                conversation_id
            ]["chat_history"]
    })

    if response.get("reservation_data"):

        conversation_memory[
            conversation_id
        ][
            "current_reservation"
        ] = response[
            "reservation_data"
        ]

    return ChatResponse(
        response=response["response"],
        intent=response["intent"],
        reservation_id=response.get("reservation_id")
    )


def _get_or_init_memory(conversation_id: str) -> dict:
    if conversation_id not in conversation_memory:
        conversation_memory[conversation_id] = {
            "chat_history": [],
            "current_reservation": None,
        }
    return conversation_memory[conversation_id]


@app.post("/chat/stream")
async def chat_stream(payload: ChatRequest):
    query = payload.query
    conversation_id = payload.conversation_id
    memory = _get_or_init_memory(conversation_id)
    memory["chat_history"].append({"role": "user", "content": query})

    # Step 1: classify intent (non-streaming, fast)
    intent_prompt = INTENT_PROMPT.format(
        chat_history=memory["chat_history"], query=query
    )
    intent_result = llm.with_structured_output(IntentOutput).invoke(intent_prompt)
    intent = intent_result.intent

    if intent == "hotel_qa":
        # Step 2: retrieve docs
        docs = retriever.invoke(query)
        context = "\n\n".join(doc.page_content for doc in docs)
        rag_prompt = RAG_PROMPT.format(context=context, question=query)

        # Step 3: stream LLM tokens
        async def generate():
            async for chunk in llm.astream(rag_prompt):
                if chunk.content:
                    yield chunk.content

        return StreamingResponse(generate(), media_type="text/plain")

    else:
        # Reservations and unsafe — run graph normally, return as one chunk
        response = graph.invoke({
            "query": query,
            "intent": None,
            "response": None,
            "reservation_data": None,
            "reservation_id": None,
            "current_reservation": memory["current_reservation"],
            "chat_history": memory["chat_history"],
        })

        if response.get("reservation_data"):
            memory["current_reservation"] = response["reservation_data"]

        async def single_chunk():
            yield response["response"]

        return StreamingResponse(single_chunk(), media_type="text/plain")