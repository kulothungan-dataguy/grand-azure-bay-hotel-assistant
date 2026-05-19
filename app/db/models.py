from alembic.config import Config
from alembic import command


def create_tables():
    """Apply any pending Alembic migrations (idempotent)."""
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
