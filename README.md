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

## Запуск

Описание появится после готовности шаблона сервиса (#18887) и стенда (#18905). Окружение целиком поднимается из репозитория `deploy`.

## Документация

Wiki проекта: https://ai.nsu.ru/projects/tusumba/wiki/Архитектура. Контракт API: OpenAPI v1 (#18892). Задачи ведутся в Redmine: https://ai.nsu.ru/projects/tusumba. Issues и Wiki GitHub выключены.

## Правила работы

Ветки, коммиты, pull request и code review описаны в [CONTRIBUTING.md](https://github.com/tusumba/.github/blob/main/CONTRIBUTING.md). Коротко:

- ветка называется `feature/<номер задачи Redmine>-<пара слов>`, например `feature/18901-login`;
- номер задачи указывается в каждом коммите и в названии PR;
- в `main` изменения попадают только через PR с одним одобрением и зелёным CI, прямой push и force push запрещены.
