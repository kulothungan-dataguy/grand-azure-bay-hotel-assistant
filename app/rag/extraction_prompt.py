EXTRACTION_PROMPT = """
You are extracting hotel reservation data from the user's message.

Previous Conversation:
{chat_history}

Current User Query:
{query}

Extract ONLY what the user has explicitly stated:
- guest_name: full name of the guest (null if not mentioned)
- email: email address (null if not mentioned)
- room_type: one of Standard, Deluxe, Suite (null if not mentioned)
- check_in_date: check-in date in YYYY-MM-DD format (null if not mentioned)
- check_out_date: check-out date in YYYY-MM-DD format (null if not mentioned)

IMPORTANT: Return null for any field not explicitly provided by the user. Do NOT invent, guess, or assume values.
"""