import os
import sqlite3

DATABASE_NAME = os.getenv("DATABASE_PATH", "hotel.db")


def get_connection():
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    return conn