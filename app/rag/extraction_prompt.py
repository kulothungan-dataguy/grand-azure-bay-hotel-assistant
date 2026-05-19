EXTRACTION_PROMPT = """
Extract reservation details from the conversation. Return null for any field the user has not explicitly stated. Do not guess or invent values.

Today's date is {today}. Use this to resolve relative dates:
- "tomorrow" = one day after today
- "day after tomorrow" = two days after today
- "next Monday" = the coming Monday
Always return dates in YYYY-MM-DD format.

Chat history: {chat_history}
User: {query}
"""
