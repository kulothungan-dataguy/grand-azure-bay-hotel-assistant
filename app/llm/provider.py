import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from app.llm.config import OLLAMA_MODEL, OPENAI_MODEL

load_dotenv()


class FallbackLLM:
    def __init__(self):
        if os.getenv("GROQ_API_KEY"):
            self.primary_llm = ChatGroq(
                model="llama-3.1-8b-instant",
                api_key=os.environ["GROQ_API_KEY"],
                temperature=0,
            )
        else:
            self.primary_llm = ChatOpenAI(
                model=OPENAI_MODEL,
                temperature=0,
            )

        self.fallback_llm = ChatOllama(model=OLLAMA_MODEL)

    def invoke(self, prompt):
        try:
            return self.primary_llm.invoke(prompt)
        except Exception as e:
            from app.utils.logger import logger
            logger.error(f"Primary LLM failed, using Ollama fallback: {e}")
            return self.fallback_llm.invoke(prompt)

    def with_structured_output(self, schema):
        return self.primary_llm.with_structured_output(schema)

    async def astream(self, prompt):
        async for chunk in self.primary_llm.astream(prompt):
            yield chunk


def get_llm():
    return FallbackLLM()
