# ticketing-service

Сервис **Ticketing & Payments** системы Tusumba: настройка продажи, билеты, покупка и оплата, записи на бесплатные мероприятия, статистика продаж.

**Ответственный:** Егор Лаухин (задача #18892).

## Что делает

- настройка продажи билетов: цена и количество;
- билеты создаются заранее строками со статусом `available`, `reserved`, `sold`; покупка резервирует их в транзакции (`FOR UPDATE SKIP LOCKED`) на ограниченное время;
- создание платежа у платёжного провайдера, приём webhook с проверкой подписи и защитой от повторной обработки;
- записи на бесплатные мероприятия, в том числе анонимные и «только для друзей»;
- список участников, «кто из друзей идёт» (данные о друзьях берёт у Identity);
- статистика продаж мероприятия (`sales_stats`);
- фоновая задача возвращает просроченные резервы в продажу.

База данных `ticketing_db`: `ticket_sales_settings`, `tickets`, `payments`, `registrations`, `sales_stats`.

## API

Внешний: `GET` и `PUT /v1/events/{id}/ticket-settings`, `POST /v1/events/{id}/purchases`, `GET /v1/purchases/{id}`, `GET /v1/me/tickets`, `GET /v1/tickets/{id}`, `PUT` и `DELETE /v1/events/{id}/registration`, `GET /v1/me/registrations`, `GET /v1/events/{id}/participants`, `GET /v1/events/{id}/friends-going`, `GET /v1/events/{id}/stats/sales`. Webhook провайдера: `POST /webhooks/payments`.

События в брокер: `TicketPurchased`, `RegistrationChanged`.

Зависит от: `events-service` (права пользователя на мероприятии), `identity-service` (друзья).

Закрывает требования: #18099, #18100, #18101, #18102 (часть про статистику продаж), #18114, #18115, #18116.

## Стек

Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, PostgreSQL 16, RabbitMQ (FastStream). Платёжный провайдер выбирается командой (кандидат — ЮKassa).

## Что уже сделано

- таблица `registrations` в схеме PostgreSQL `ticketing` (миграция Alembic), одна запись на пару «мероприятие, пользователь» (#19051);
- `PUT /v1/events/{id}/registration` - «Пойду» или «Интересно» на бесплатное мероприятие, видимость `public`, `friends_only`, `anonymous`; повторный запрос меняет статус и видимость записи, а не создаёт вторую;
- `DELETE /v1/events/{id}/registration` - отмена записи; запись по купленному билету и запись на прошедшее мероприятие не отменяются;
- `GET /v1/me/registrations` - мои записи, новые первыми, пагинация `page` и `size`;
- признак `is_free`, дату и статус мероприятия сервис берёт у events-service (`GET /internal/events/{id}`); мероприятие прошло, если его дата раньше сегодняшней по Новосибирску или статус `held`, `not_held`;
- после создания, изменения или отмены записи в брокер через outbox уходит `RegistrationChanged`.

Продажа и покупка билетов, участники и «кто из друзей идёт» - в следующих задачах.

## Запуск

Сервис создан из [service-template](https://github.com/tusumba/service-template). Окружение целиком поднимается из репозитория `deploy`.

```bash
uv sync
cp .env.example .env
uv run python -m tusumba_common.testing dev-keys   # тестовая пара ключей, впишите public.pem в JWT_PUBLIC_KEY
docker compose up -d postgres rabbitmq
uv run alembic upgrade head
uv run --env-file .env uvicorn app.main:create_app --factory --reload
```

| Переменная | По умолчанию | Что это |
|---|---|---|
| `DATABASE_URL` | обязательна | `postgresql+asyncpg://user:password@host:5432/db` |
| `RABBITMQ_URL` | обязательна | адрес RabbitMQ |
| `EVENTS_URL` | `http://events:8000` | адрес events-service для `/internal` |
| `JWT_PUBLIC_KEY` | обязательна | публичный ключ Identity в PEM (tusumba-common) |
| `SERVICE_TOKEN` | обязательна | сервисный токен для `X-Service-Token` (tusumba-common) |

## Проверки

Тестам нужен Docker: PostgreSQL и RabbitMQ поднимаются через testcontainers.

```bash
uv run ruff format .
uv run ruff check .
uv run mypy app tests migrations
uv run pytest
```

## Документация

- [OpenAPI v1](docs/openapi.yaml) - API раздела «Билеты и записи» архитектуры.
- [Модель данных](docs/data-model.md) - таблицы записей, билетов, резервов и платежей, коды ошибок.

Wiki проекта: https://ai.nsu.ru/projects/tusumba/wiki/Архитектура. Контракт API: OpenAPI v1 (#18892). Задачи ведутся в Redmine: https://ai.nsu.ru/projects/tusumba. Issues и Wiki GitHub выключены.

