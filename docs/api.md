# HTTP API и демонстрация

Интерактивное описание доступно после запуска по адресу `/docs`.

## Маршруты

| Метод и путь | Назначение |
| --- | --- |
| `GET /health` | процесс приложения работает |
| `GET /ready` | приложение подключается к БД |
| `POST /api/v1/sellers` | создать продавца |
| `GET /api/v1/sellers/{id}` | получить продавца |
| `POST /api/v1/buyers` | создать покупателя |
| `GET /api/v1/buyers/{id}` | получить покупателя |
| `POST /api/v1/auctions` | создать аукцион |
| `GET /api/v1/auctions/{id}` | получить аукцион |
| `POST /api/v1/auctions/{id}/lots` | добавить лот |
| `GET /api/v1/lots/{id}` | получить лот |
| `POST /api/v1/auctions/{id}/open` | открыть аукцион |
| `POST /api/v1/auctions/{id}/close` | закрыть аукцион |
| `POST /api/v1/sales` | зарегистрировать продажу |
| `GET /api/v1/reports/revenue` | получить отчёт; фильтр `auction_id` необязателен |


### 1. Создать продавца

```bash
curl -X POST http://127.0.0.1:8000/api/v1/sellers \
  -H 'Content-Type: application/json' \
  -d '{"name":"Анна","email":"seller@example.com"}'
```

### 2. Создать покупателя

```bash
curl -X POST http://127.0.0.1:8000/api/v1/buyers \
  -H 'Content-Type: application/json' \
  -d '{"name":"Борис","email":"buyer@example.com"}'
```

### 3. Создать аукцион

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auctions \
  -H 'Content-Type: application/json' \
  -d '{"title":"Аукцион картин","starts_at":"2026-09-06T10:00:00+03:00","ends_at":"2026-09-06T12:00:00+03:00"}'
```

### 4. Добавить лот и открыть аукцион

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auctions/1/lots \
  -H 'Content-Type: application/json' \
  -d '{"seller_id":1,"title":"Картина","starting_price":"100.00"}'

curl -X POST http://127.0.0.1:8000/api/v1/auctions/1/open
```

### 5. Продать лот

```bash
curl -X POST http://127.0.0.1:8000/api/v1/sales \
  -H 'Content-Type: application/json' \
  -d '{"lot_id":1,"buyer_id":1,"final_price":"150.00"}'
```

Повторить запрос: сервис должен вернуть `409` и код `LOT_ALREADY_SOLD`.

### 6. Получить отчёт и закрыть аукцион

```bash
curl 'http://127.0.0.1:8000/api/v1/reports/revenue?auction_id=1'
curl -X POST http://127.0.0.1:8000/api/v1/auctions/1/close
```

