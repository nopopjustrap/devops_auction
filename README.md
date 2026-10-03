# Auction Service — ЛР1 / ЛР3

Учебная система учёта аукционов, лотов, участников и продаж: FastAPI,
SQLite, сессии оператора и адаптивный HTML/CSS/JavaScript-интерфейс.
Версия приложения: **0.2.0**. Опубликованные теги v0.1.0 и v0.1.1 сохраняются.

## Быстрый старт

Требуются Linux (включая Ubuntu/WSL), Python 3.12 с venv и GNU Make.

```bash
make setup
make migrate
make verify
make run
```

Открываем http://127.0.0.1:8000. На новой БД создаём первого оператора.
Для **существующей БД** сначала останавливаем приложение и сохраняем копию:

```bash
make setup
make backup
make migrate
make verify
make run
```

Backup выводит путь копии. Миграции сохраняют данные v0.1.1, пользователя и
сессии. Не удаляем БД для обновления. Используем одинаковый DATABASE_PATH во
всех командах: `data/demo.db` и `data/auctions.db` — разные базы и операторы.

## Возможности

- первая регистрация, вход, серверные сессии, защищённый API и выход;
- создание/чтение участников и аукционов, добавление/просмотр лотов;
- статусы аукциона DRAFT → OPEN → CLOSED и лота DRAFT → AVAILABLE → SOLD/UNSOLD;
- транзакционная продажа, запрет повторной продажи и цены ниже стартовой;
- комиссия аукциона, сохранённая комиссия продажи, отчёт о выручке и сумме продавцам;
- Alembic: три последовательные миграции и обновление старой SQLite;
- backup/restore с проверкой копии и защитой от неявной перезаписи;
- unit/API/БД-тесты, SAST, отчёты покрытия и проверка трёх мутаций.

## Команды

| Команда | Назначение |
| --- | --- |
| `make setup` | .venv, точные зависимости, безопасное создание .env |
| `make migrate` | Применить миграции до 003 |
| `make run` | Локальный Uvicorn с --reload |
| `make quality` | Ruff и проверка форматирования |
| `make security` | Bandit для app и migrations |
| `make test` | Все тесты, JUnit, coverage (порог 85%), FR coverage (порог 40%) |
| `make verify` | pip check → quality → security → test → mutation-check |
| `make migration-check` | Проверки миграций отдельно |
| `make backup` | Новая проверенная копия в backups/ |
| `make restore BACKUP_FILE=… APP_STOPPED=1` | Восстановление после остановки приложения |
| `make backup-check` | Тесты резервного копирования и восстановления |
| `make backup-demo` | Намеренное удаление и восстановление временных данных |
| `make mutation-check` | Три целевые ошибки в временных копиях |
| `make clean` | Удалить отчёты и coverage, сохранить БД |

При восстановлении поверх существующего файла дополнительно нужен
`RESTORE_REPLACE=1`; прежние байты сохраняются рядом. Подробности и ограничения:
[отчёт ЛР3](docs/lr3.md).

## Конфигурация

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| APP_NAME | Auction Service | Название OpenAPI |
| DATABASE_PATH | data/auctions.db | Путь к SQLite |
| SESSION_TTL_HOURS | 8 | Срок сессии |
| COOKIE_SECURE | false | Включить true при HTTPS |

`.env` загружает Makefile и не сохраняет в Git. При прямом запуске Python
передаём переменные окружения явно. Основная БД не используется тестами.

Служебные адреса: `/health` — процесс жив; `/ready` — доступна актуальная схема;
`/docs` — Swagger; `/openapi.json` — OpenAPI. Существующую старую БД сначала
обновляем командой migrate. `/ready` при потере файла возвращает 503.

## Документация

- [Отчёт о выполнении ЛР3](docs/lr3.md)
- [Фактическая проверка реализации](docs/verification-lr3.md)
- [Техническое задание](docs/technical-spec.md)
- [API](docs/api.md)
- [Модель данных](docs/data-model.md)
- [Соответствие ЛР1](docs/requirements.md)
- [Git-процесс](docs/git-process.md)
- [Правила изменений](CONTRIBUTING.md)
