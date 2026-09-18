# HTTP API и рабочий сценарий

Базовый адрес локального приложения: `http://127.0.0.1:8000`.
Интерактивное описание OpenAPI доступно по адресу `/docs`.

## Доступ к API

`/health`, `/ready`, веб-интерфейс и операции регистрации/входа доступны
без сессии. Все операции с участниками, аукционами, лотами, продажами и
отчётами требуют cookie `auction_session`.

| Метод и путь | Доступ | Назначение |
| --- | --- | --- |
| `GET /` | публичный | веб-интерфейс |
| `GET /health` | публичный | процесс приложения работает |
| `GET /ready` | публичный | приложение подключается к БД |
| `GET /api/v1/auth/status` | публичный | доступна ли первая регистрация |
| `POST /api/v1/auth/register` | публичный один раз | создать первого оператора |
| `POST /api/v1/auth/login` | публичный | создать сессию и установить cookie |
| `GET /api/v1/auth/me` | сессия | получить текущего оператора |
| `POST /api/v1/auth/logout` | cookie необязательна | удалить сессию и cookie |
| `POST /api/v1/sellers` | сессия | создать продавца |
| `GET /api/v1/sellers/{id}` | сессия | получить продавца |
| `POST /api/v1/buyers` | сессия | создать покупателя |
| `GET /api/v1/buyers/{id}` | сессия | получить покупателя |
| `POST /api/v1/auctions` | сессия | создать аукцион |
| `GET /api/v1/auctions/{id}` | сессия | получить аукцион |
| `POST /api/v1/auctions/{id}/lots` | сессия | добавить лот |
| `GET /api/v1/auctions/{id}/lots` | сессия | получить лоты аукциона |
| `GET /api/v1/lots/{id}` | сессия | получить лот |
| `POST /api/v1/auctions/{id}/open` | сессия | открыть аукцион |
| `POST /api/v1/auctions/{id}/close` | сессия | закрыть аукцион |
| `POST /api/v1/sales` | сессия | зарегистрировать продажу |
| `GET /api/v1/reports/revenue` | сессия | получить отчёт по выручке |

В Swagger защищённые операции отмечены схемой `SessionCookie`.

## Аутентификация через curl

Cookie-файл размещаем во временном каталоге, а не в репозитории.

### 1. Зарегистрировать первого оператора

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"operator","password":"student123"}'
```

Повторная регистрация возвращает `409 REGISTRATION_CLOSED`.

### 2. Войти и сохранить cookie

```bash
curl -c /tmp/auction-cookies.txt \
  -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"operator","password":"student123"}'
```

### 3. Выполнить защищённую операцию

```bash
curl -b /tmp/auction-cookies.txt \
  http://127.0.0.1:8000/api/v1/auth/me
```

Без действующей cookie защищённый маршрут возвращает `401 AUTH_REQUIRED`.

## Полный бизнес-сценарий

Во всех следующих запросах используется параметр
`-b /tmp/auction-cookies.txt`.

### 1. Создать продавца

```bash
curl -b /tmp/auction-cookies.txt \
  -X POST http://127.0.0.1:8000/api/v1/sellers \
  -H 'Content-Type: application/json' \
  -d '{"name":"Анна","email":"seller@example.com"}'
```

### 2. Создать покупателя

```bash
curl -b /tmp/auction-cookies.txt \
  -X POST http://127.0.0.1:8000/api/v1/buyers \
  -H 'Content-Type: application/json' \
  -d '{"name":"Борис","email":"buyer@example.com"}'
```

### 3. Создать аукцион

```bash
curl -b /tmp/auction-cookies.txt \
  -X POST http://127.0.0.1:8000/api/v1/auctions \
  -H 'Content-Type: application/json' \
  -d '{"title":"Аукцион картин","starts_at":"2026-09-19T10:00:00+03:00","ends_at":"2026-09-19T12:00:00+03:00"}'
```

### 4. Добавить лот и открыть аукцион

```bash
curl -b /tmp/auction-cookies.txt \
  -X POST http://127.0.0.1:8000/api/v1/auctions/1/lots \
  -H 'Content-Type: application/json' \
  -d '{"seller_id":1,"title":"Картина","starting_price":"100.00"}'

curl -b /tmp/auction-cookies.txt \
  -X POST http://127.0.0.1:8000/api/v1/auctions/1/open
```

Открыть аукцион без лотов нельзя: возвращается
`409 AUCTION_HAS_NO_LOTS`.

### 5. Зарегистрировать продажу

```bash
curl -b /tmp/auction-cookies.txt \
  -X POST http://127.0.0.1:8000/api/v1/sales \
  -H 'Content-Type: application/json' \
  -d '{"lot_id":1,"buyer_id":1,"final_price":"150.00"}'
```

Повторная продажа возвращает `409 LOT_ALREADY_SOLD`, а цена ниже стартовой —
`409 PRICE_BELOW_STARTING_PRICE`.

### 6. Получить данные и закрыть аукцион

```bash
curl -b /tmp/auction-cookies.txt \
  http://127.0.0.1:8000/api/v1/auctions/1/lots

curl -b /tmp/auction-cookies.txt \
  'http://127.0.0.1:8000/api/v1/reports/revenue?auction_id=1'

curl -b /tmp/auction-cookies.txt \
  -X POST http://127.0.0.1:8000/api/v1/auctions/1/close
```

### 7. Выйти

```bash
curl -b /tmp/auction-cookies.txt \
  -X POST http://127.0.0.1:8000/api/v1/auth/logout
rm /tmp/auction-cookies.txt
```

## Формат ошибки

```json
{
  "error": {
    "code": "AUCTION_NOT_FOUND",
    "message": "Auction с id=999 не найден",
    "details": {}
  }
}
```

Основные HTTP-статусы: `401` для отсутствующей или неверной аутентификации,
`404` для отсутствующего объекта, `409` для конфликта бизнес-правил,
`422` для некорректного тела запроса и `503` для недоступной БД.
