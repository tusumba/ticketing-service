# Модель данных Ticketing & Payments

Задача: [#18892 - OpenAPI v1 и модель данных: Ticketing & Payments](https://ai.nsu.ru/issues/18892).
Источник: [архитектура Tusumba](https://ai.nsu.ru/projects/tusumba/wiki/Архитектура),
раздел «Ticketing & Payments (ticketing_db)».

Таблицы продажи (`ticket_sales_settings`, `tickets`, `reservations`, `payments`, `sales_stats`) - черновик,
реализация в Спринте 3. Суммы хранятся в копейках (`integer`), валюта - `RUB`.

## registrations

Записи пользователей на мероприятия: бесплатные и созданные покупкой билета.

| Поле | Тип | Ключ |
|---|---|---|
| id | uuid | PK |
| event_id | uuid | |
| user_id | uuid | |
| status | enum (going, interested) | |
| visibility | enum (public, friends_only, anonymous) | |
| source | enum (free_signup, ticket) | |
| created_at | timestamptz | |

Уникальность: (`event_id`, `user_id`) - одна запись пользователя на мероприятие.

- `status`: `going` - «Пойду», `interested` - «Интересно».
- `source`: `free_signup` - бесплатная запись; `ticket` - запись создана при успешной оплате
  (`status = going`, `visibility = public`).
- Отмена бесплатной записи удаляет строку, запись с `source = ticket` отменить нельзя.

## ticket_sales_settings

Настройки продажи билетов платного мероприятия. Платное оно или нет, определяет `is_free`
у events-service, строка настроек может появиться позже самого мероприятия.

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
| status | enum (created, succeeded, failed, cancelled) | |
| confirmation_url | text, null | |
| created_at | timestamptz | |
| updated_at | timestamptz | |

`provider_payment_id` уникален: повторный webhook находит тот же платёж и не обрабатывает его второй раз.

## sales_stats

Статистика продаж мероприятия. Обновляется по успешным платежам, неоплаченные и отменённые покупки
в неё не попадают.

| Поле | Тип | Ключ |
|---|---|---|
| event_id | uuid | PK |
| tickets_sold | integer | |
| revenue_amount | integer | |
| currency | text | |
| updated_at | timestamptz | |

## Внешние связи

`registrations.event_id`, `ticket_sales_settings.event_id`, `tickets.event_id`, `reservations.event_id` и `sales_stats.event_id`
ссылаются на `events_db.events.id` по идентификатору, без внешнего ключа.
`registrations.user_id`, `tickets.owner_id` и `reservations.user_id` ссылаются на `identity_db.users.id`
по идентификатору, без внешнего ключа.

## Жизненный цикл покупки (Спринт 3)

1. `POST /v1/events/{id}/purchases`: в одной транзакции выбираются `quantity` билетов со статусом `available`
   (`SELECT ... FOR UPDATE SKIP LOCKED`), они переходят в `reserved`, создаётся `reservations` (`pending`,
   `expires_at` = сейчас + 15 минут) и `payments` (`created`) у провайдера.
2. Webhook об успешной оплате: `payments.status` → `succeeded`, `reservations.status` → `paid`,
   билеты → `sold`, создаётся `registrations` (`source = ticket`; если запись уже есть, вторая не создаётся),
   обновляется `sales_stats`, публикуется `TicketPurchased`.
3. Webhook о неудачной оплате или отмене: `payments.status` → `failed` или `cancelled`,
   `reservations.status` → `failed`, билеты → `available`.
4. Фоновая задача: резервы `pending` с прошедшим `expires_at` → `expired`, `payments.status` → `cancelled`,
   билеты → `available`.

## API

| Запрос | Назначение | Доступ |
|---|---|---|
| PUT /v1/events/{id}/registration | Запись на бесплатное мероприятие («Пойду» или «Интересно»), смена статуса или видимости | Пользователь |
| DELETE /v1/events/{id}/registration | Отмена записи | Пользователь |
| GET /v1/me/registrations | Мои записи | Пользователь |
| GET /v1/me/tickets | Мои билеты | Пользователь |
| GET /v1/tickets/{id} | Билет | Владелец билета |
| GET /v1/events/{id}/participants | Список участников | Владелец, администратор мероприятия |
| GET /v1/events/{id}/friends-going | Кто из друзей идёт | Пользователь |
| GET /v1/events/{id}/ticket-settings | Настройки продажи (черновик) | Пользователь |
| PUT /v1/events/{id}/ticket-settings | Настройка продажи (черновик) | Владелец, администратор мероприятия |
| POST /v1/events/{id}/purchases | Покупка билетов (черновик) | Пользователь |
| GET /v1/purchases/{id} | Статус покупки (черновик) | Покупатель |
| POST /webhooks/payments | Уведомление провайдера (черновик) | Платёжный провайдер, проверка подписи |

## Коды ошибок

Формат ошибки: `{"error": {"code": "...", "message": "..."}}`, для `validation_error` дополнительно `details`.

| HTTP | code | Когда |
|---|---|---|
| 401 | not_authenticated | Нет заголовка Authorization (tusumba-common) |
| 401 | token_expired | Срок действия access-токена истёк (tusumba-common) |
| 401 | invalid_token | Токен недействителен или не access (tusumba-common) |
| 403 | forbidden | Нет нужной роли в команде мероприятия |
| 404 | event_not_found | Мероприятие не найдено или недоступно; «Мероприятие недоступно.» |
| 404 | registration_not_found | Пользователь не записан на мероприятие |
| 404 | ticket_not_found | Билет не найден или принадлежит другому пользователю |
| 404 | ticket_settings_not_found | Продажа билетов не настроена |
| 409 | registration_from_ticket | Отмена записи, созданной покупкой билета |
| 404 | purchase_not_found | Покупка не найдена |
| 409 | event_is_paid | Запись на платное мероприятие, нужно купить билет |
| 409 | event_is_free | Покупка билета или настройка продажи на бесплатном мероприятии |
| 409 | event_finished | Мероприятие уже прошло |
| 409 | event_has_registrations | Настройка продажи, когда уже есть записи с `source = free_signup` |
| 409 | quantity_below_sold | Билетов меньше, чем продано и зарезервировано |
| 409 | tickets_sold_out | Свободных билетов меньше, чем запрошено |
| 409 | sales_closed | Продажа не настроена, не открыта или мероприятие прошло |
| 422 | validation_error | Тело или параметры запроса не прошли проверку |
| 400 | invalid_signature | Подпись webhook не прошла проверку |
| 502 | payment_provider_error | Платёжный провайдер недоступен |
