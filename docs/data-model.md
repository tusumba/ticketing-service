# Модель данных Ticketing & Payments

Задача: [#18892 - OpenAPI v1 и модель данных: Ticketing & Payments](https://ai.nsu.ru/issues/18892).
Источник: [архитектура Tusumba](https://ai.nsu.ru/projects/tusumba/wiki/Архитектура),
раздел «Ticketing & Payments (ticketing_db)».

Таблицы продажи (`ticket_sales_settings`, `tickets`, `reservations`, `payments`) - черновик,
реализация в Спринте 3. Суммы хранятся в копейках (`integer`), валюта - `RUB`.

## registrations

Записи на бесплатные мероприятия.

| Поле | Тип | Ключ |
|---|---|---|
| id | uuid | PK |
| event_id | uuid | |
| user_id | uuid | |
| visibility | enum (public, friends, anonymous) | |
| created_at | timestamptz | |

Уникальность: (`event_id`, `user_id`) - одна запись пользователя на мероприятие.
Отмена записи удаляет строку.

## ticket_sales_settings

Настройки продажи билетов. Наличие строки означает, что мероприятие платное.

| Поле | Тип | Ключ |
|---|---|---|
| event_id | uuid | PK |
| price_amount | integer | |
| currency | text | |
| quantity | integer | |
| sales_open | boolean | |
| updated_at | timestamptz | |

## tickets

Билеты. Создаются заранее по `quantity` из настроек продажи.

| Поле | Тип | Ключ |
|---|---|---|
| id | uuid | PK |
| event_id | uuid | FK → ticket_sales_settings.event_id |
| status | enum (available, reserved, sold) | |
| reservation_id | uuid, null | FK → reservations.id |
| owner_id | uuid, null | |
| code | text, null | UNIQUE |
| price_amount | integer, null | |
| sold_at | timestamptz, null | |

Индекс: (`event_id`, `status`) - поиск свободных билетов.

- `available` - билет свободен, `reservation_id` и `owner_id` пустые;
- `reserved` - билет зарезервирован покупкой `reservation_id`;
- `sold` - билет оплачен, заполнены `owner_id`, `code` (для QR), `price_amount` (цена на момент покупки) и `sold_at`.

## reservations

Резервы билетов. Одна строка - одна покупка (`/v1/purchases/{id}`).

| Поле | Тип | Ключ |
|---|---|---|
| id | uuid | PK |
| event_id | uuid | |
| user_id | uuid | |
| quantity | integer | |
| total_amount | integer | |
| status | enum (pending, paid, expired, failed) | |
| idempotency_key | uuid | |
| expires_at | timestamptz | |
| created_at | timestamptz | |

Уникальность: (`user_id`, `idempotency_key`) - защита от двойной покупки.
Индекс: (`status`, `expires_at`) - фоновая задача ищет просроченные резервы.

## payments

Платежи у платёжного провайдера.

| Поле | Тип | Ключ |
|---|---|---|
| id | uuid | PK |
| reservation_id | uuid | FK → reservations.id |
| provider | text | |
| provider_payment_id | text | UNIQUE |
| amount | integer | |
| currency | text | |
| status | enum (pending, succeeded, canceled) | |
| confirmation_url | text, null | |
| created_at | timestamptz | |
| updated_at | timestamptz | |

`provider_payment_id` уникален: повторный webhook находит тот же платёж и не обрабатывает его второй раз.

## Внешние связи

`registrations.event_id`, `ticket_sales_settings.event_id`, `tickets.event_id` и `reservations.event_id`
ссылаются на `events_db.events.id` по идентификатору, без внешнего ключа.
`registrations.user_id`, `tickets.owner_id` и `reservations.user_id` ссылаются на `identity_db.users.id`
по идентификатору, без внешнего ключа.

## Жизненный цикл покупки (Спринт 3)

1. `POST /v1/events/{id}/purchases`: в одной транзакции выбираются `quantity` билетов со статусом `available`
   (`SELECT ... FOR UPDATE SKIP LOCKED`), они переходят в `reserved`, создаётся `reservations` (`pending`,
   `expires_at` = сейчас + 15 минут) и `payments` (`pending`) у провайдера.
2. Webhook об успешной оплате: `payments.status` → `succeeded`, `reservations.status` → `paid`,
   билеты → `sold`, публикуется `TicketPurchased`.
3. Webhook об отмене платежа: `payments.status` → `canceled`, `reservations.status` → `failed`,
   билеты → `available`.
4. Фоновая задача: резервы `pending` с прошедшим `expires_at` → `expired`, билеты → `available`.

## API

| Запрос | Назначение | Доступ |
|---|---|---|
| PUT /v1/events/{id}/registration | Запись на бесплатное мероприятие или смена видимости | Пользователь |
| DELETE /v1/events/{id}/registration | Отмена записи | Пользователь |
| GET /v1/me/registrations | Мои записи | Пользователь |
| GET /v1/me/tickets | Мои билеты | Пользователь |
| GET /v1/tickets/{id} | Билет | Владелец билета |
| GET /v1/events/{id}/participants | Список участников | Пользователь, полный список - команда мероприятия |
| GET /v1/events/{id}/ticket-settings | Настройки продажи (черновик) | Пользователь |
| PUT /v1/events/{id}/ticket-settings | Настройка продажи (черновик) | Владелец, администратор мероприятия |
| POST /v1/events/{id}/purchases | Покупка билетов (черновик) | Пользователь |
| GET /v1/purchases/{id} | Статус покупки (черновик) | Покупатель |
| POST /webhooks/payments | Уведомление провайдера (черновик) | Платёжный провайдер, проверка подписи |

## Коды ошибок

Формат ошибки: `{"code": "...", "message": "..."}`, для `validation_error` дополнительно `details`.

| HTTP | code | Когда |
|---|---|---|
| 401 | unauthorized | Нет токена или токен недействителен |
| 403 | forbidden | Нет нужной роли в команде мероприятия |
| 404 | event_not_found | Мероприятие не найдено |
| 404 | registration_not_found | Пользователь не записан на мероприятие |
| 404 | ticket_not_found | Билет не найден или принадлежит другому пользователю |
| 404 | ticket_settings_not_found | Продажа билетов не настроена |
| 404 | purchase_not_found | Покупка не найдена |
| 409 | event_is_paid | Запись на платное мероприятие, нужно купить билет |
| 409 | event_is_free | Покупка билета на бесплатное мероприятие |
| 409 | event_finished | Мероприятие уже прошло |
| 409 | event_not_published | Мероприятие не опубликовано |
| 409 | event_has_registrations | Настройка продажи, когда уже есть записи |
| 409 | quantity_below_sold | Билетов меньше, чем продано и зарезервировано |
| 409 | tickets_sold_out | Свободных билетов меньше, чем запрошено |
| 409 | sales_closed | Продажа не открыта |
| 422 | validation_error | Тело или параметры запроса не прошли проверку |
| 400 | invalid_signature | Подпись webhook не прошла проверку |
| 502 | payment_provider_error | Платёжный провайдер недоступен |
