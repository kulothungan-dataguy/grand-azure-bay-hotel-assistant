EXTRACTION_PROMPT = """
You are extracting hotel reservation data.

Previous Conversation:
{chat_history}

Extract:

- guest_name
- email
- room_type
- check_in_date
- check_out_date

Current User Query:
{query}
"""