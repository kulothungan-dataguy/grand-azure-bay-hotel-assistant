import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from app.llm.config import OPENAI_MODEL

try:
    from langchain_groq import ChatGroq
    _has_groq = True
except ImportError:
    _has_groq = False

load_dotenv()

# Thread-safe counters for health/metrics endpoint
fallback_stats: dict[str, int] = {
    "primary_calls": 0,
    "fallback_calls": 0,
    "primary_errors": 0,
}


class FallbackLLM:
    def __init__(self):
        self.primary_llm = ChatOpenAI(model=OPENAI_MODEL, temperature=0, max_tokens=1024)

        if _has_groq and os.getenv("GROQ_API_KEY"):
            self.fallback_llm = ChatGroq(
                model="llama-3.1-8b-instant",
                api_key=os.environ["GROQ_API_KEY"],
                temperature=0,
            )
        else:
            self.fallback_llm = None

    def invoke(self, prompt):
        fallback_stats["primary_calls"] += 1
        try:
            return self.primary_llm.invoke(prompt)
        except Exception as e:
            from app.utils.logger import logger
            fallback_stats["primary_errors"] += 1
            logger.error(f"OpenAI failed: {e}")
            if self.fallback_llm:
                fallback_stats["fallback_calls"] += 1
                logger.info("Falling back to Groq")
                return self.fallback_llm.invoke(prompt)
            raise

    def with_structured_output(self, schema):
        return self.primary_llm.with_structured_output(schema)

    async def astream(self, prompt):
        fallback_stats["primary_calls"] += 1
        try:
            async for chunk in self.primary_llm.astream(prompt):
                yield chunk
        except Exception as e:
            from app.utils.logger import logger
            fallback_stats["primary_errors"] += 1
            logger.error(f"OpenAI astream failed: {e}")
            if self.fallback_llm:
                fallback_stats["fallback_calls"] += 1
                logger.info("Falling back to Groq")
                result = self.fallback_llm.invoke(prompt)
                yield result
            else:
                raise


def get_llm():
    return FallbackLLM()
