EXTRACTION_PROMPT = """
Extract reservation details from the conversation. Return null for any field the user has not explicitly stated. Do not guess or invent values.

Chat history: {chat_history}
User: {query}
"""