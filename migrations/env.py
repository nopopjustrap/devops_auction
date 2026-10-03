"""Alembic uses the explicit connection supplied by app.migrate."""

from alembic import context

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("Use make migrate (DATABASE_PATH selects the database)")
context.configure(connection=connection, transactional_ddl=True)
with context.begin_transaction():
    context.run_migrations()
