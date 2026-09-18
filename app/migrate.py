"""Команда создания схемы: python -m app.migrate."""

from app.db import database_path_from_env, init_db


def main() -> None:
    database_path = database_path_from_env()
    init_db(database_path)
    print(f"Database schema is ready: {database_path}")


if __name__ == "__main__":
    main()
