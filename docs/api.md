# REST API

Базовый адрес: `https://<домен>/api/v1`. Те же маршруты доступны по `/api`: их использует веб-интерфейс.

## Авторизация

Ключ создаётся в профиле (`/profile/api`) и показывается один раз:

```http
Authorization: Bearer dk_live_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

Запросы с ключом выполняются от имени владельца ключа и видят только его документы. В браузере вместо ключа используется сессионная cookie. Для запросов с cookie сервер дополнительно сверяет `Origin`.

## Ошибки

Ошибки возвращаются с HTTP-кодом и JSON:

```json
{"error": "not_found", "message": "Документ не найден или был удалён."}
```

| Код | `error` | Когда |
| --- | --- | --- |
| 400 | `bad_type`, `no_files`, `too_many_files`, `bad_question`, `invalid_email`, `weak_password` | Неверный запрос |
| 401 | `unauthorized`, `bad_credentials` | Нет или неверный ключ, сессия или пароль |
| 403 | `forbidden_origin` | Запрос с cookie с чужого источника |
| 404 | `not_found` | Документа нет, он чужой или ещё не готов |
| 409 | `not_ready`, `email_taken` | Документ ещё распознаётся; почта занята |
| 429 | — | Превышен лимит запросов (nginx) |

## Документы

### Загрузить

`POST /documents` — `multipart/form-data`

| Поле | |
| --- | --- |
| `files` | Один или несколько файлов, до 20. PNG, JPG или одностраничный PDF, до 10 МБ каждый |
| `document_type` | `auto` (по умолчанию), `study_certificate`, `academic_leave_application`, `internship_certificate` или ключ типа из конструктора (`GET /types`) |

```bash
curl -X POST https://dekanat.karpovprod.ru/api/v1/documents \
  -H "Authorization: Bearer $DK_KEY" \
  -F document_type=auto -F files=@spravka.pdf -F files=@zayavlenie.png
```

Ответ `202`. Файлы, которые не прошли проверку, попадают в `rejected`, остальные встают в очередь:

```json
{
  "documents": [
    {"slug": "d818jqzlw-t9mwrhi-rzd01", "filename": "spravka.pdf", "status": "queued",
     "queue_position": 1, "url": "/check/d818jqzlw-t9mwrhi-rzd01", "...": "..."}
  ],
  "rejected": [{"filename": "scan.docx", "message": "Поддерживаются PDF, JPG и PNG."}]
}
```

### Список

`GET /documents` → `{"documents": [summary, …]}`, новые первыми.

### Документ

`GET /documents/{slug}`

```json
{
  "slug": "d818jqzlw-t9mwrhi-rzd01",
  "filename": "Справка_о_практике.png",
  "status": "done",
  "document_type": "internship_certificate",
  "found": 8, "total": 10, "valid": false,
  "approved": false, "approved_by": null,
  "verified": {"student_name": true},
  "seconds": 3.6,
  "analysis": {
    "document_type": "internship_certificate",
    "detected_type": "internship_certificate",
    "type_matches": true,
    "fields": {
      "student_name": "Целшархорцелов Арсений Родионович",
      "organization": "ООО «Серебряный контур»",
      "internship_start": "2032-01-01",
      "internship_end": "2032-04-14",
      "supervisor_name": "Белчевталлютин Родион Игнатьевич",
      "grade": "хорошо",
      "document_number": "УК-46922",
      "issue_date": "2032-05-04",
      "signature_present": false,
      "seal_present": false
    },
    "validation": {"status": "missing_fields", "missing_fields": ["signature_present", "seal_present"], "sources": ["rule:5.2", "rule:5.3"]},
    "review": {"student_name": true, "supervisor_name": true, "grade": false},
    "confidence": {"student_name": 0.62, "grade": 0.99, "signature_present": 0.97},
    "ocr_text": "СПРАВКА О ПРАКТИКЕ\nФИО студента: …",
    "model": {"decoder": "cuda_graph_static_cache", "seconds": 3.4, "token_budget_reached": false, "visual_passes": 1}
  },
  "regions": {"status": "done", "regions": [{"field": "student_name", "page": 0, "bbox": [0.06, 0.08, 0.53, 0.1]}]},
  "chat": [],
  "preview_url": "/api/documents/d818jqzlw-t9mwrhi-rzd01/preview",
  "file_url": "/api/documents/d818jqzlw-t9mwrhi-rzd01/file"
}
```

Пояснения к полям ответа:

- **`status`** — `queued`, `running`, `done` или `failed`; при ошибке её текст в поле `error`.
- **`fields`** — текстовые значения или `"не найдено"`, даты в формате ISO; `signature_present` и `seal_present` — `true` или `false`.
- **`validation.status`** — `document_ok` или `missing_fields`; в `sources` перечислены пункты Положения.
- **`review`** — поля с пометкой «Проверьте».
- **`confidence`** — минимальная вероятность токенов значения, у отметок — оценка головы.
- **`regions.bbox`** — доли ширины и высоты страницы `[x0, y0, x1, y1]`.

`GET /documents/{slug}/preview` — PNG для просмотра. `GET /documents/{slug}/file` — исходный файл.

`DELETE /documents/{slug}` — удалить документ и его файлы. Студент удаляет только свой черновик, сотрудник — закрытую заявку.

### Сменить тип

`POST /documents/{slug}/type` с телом `{"document_type": "study_certificate"}`. Конвейер перечитывает документ с выбранным типом, цельная модель пересчитывает поля из уже прочитанного текста. Сверка и решение сбрасываются.

### Отметить поле как сверенное

`POST /documents/{slug}/verify` с телом `{"field": "student_name", "verified": true}` → `{"verified": {...}}`. Только для сотрудников деканата.

## Заявки

| Запрос | Кто | Действие |
| --- | --- | --- |
| `POST /documents/{slug}/submit` `{"comment": "…"}` | Владелец | Отправить черновик или возвращённую заявку в деканат |
| `GET /documents/{slug}?open=1` | Сотрудник | Открыть заявку: состояние `submitted` → `review` |
| `POST /documents/{slug}/approve` `{"decision": "approved"}` | Сотрудник | Одобрить |
| `POST /documents/{slug}/approve` `{"decision": "returned", "comment": "…"}` | Сотрудник | Вернуть на доработку; комментарий обязателен |
| `POST /documents/{slug}/approve` `{"decision": null}` | Сотрудник | Отменить решение |
| `POST /documents/{slug}/replace` (multipart `file`) | Владелец, сотрудник | Заменить файл в той же заявке; прежняя версия сохраняется |
| `POST /documents/{slug}/close` `{"comment": "…"}` | Сотрудник | Закрыть заявку |
| `GET /documents/{slug}/history` | Владелец, сотрудник | Журнал событий и список версий |
| `GET /documents/{slug}/versions/{n}/file` | Владелец, сотрудник | Файл версии `n` |
| `GET /documents/{slug}/protocol.pdf` | Владелец, сотрудник | PDF-протокол проверки |
| `GET /staff/export.xlsx?type=&group=&state=` | Сотрудник | Выгрузка заявок и журнала в Excel |

Состояния: `draft`, `submitted`, `review`, `approved`, `returned`, `closed`. Карточка документа (`GET /documents/{slug}`) содержит `state`, `attempts`, `version`, `submit_warning` (текст предупреждения или `null`), `name_check` и `can` — какие действия доступны текущему пользователю.

## Типы документов

| Запрос | Кто | Действие |
| --- | --- | --- |
| `GET /types` | Все | Встроенные и добавленные типы с полями |
| `POST /admin/types` | Суперадмин | Создать тип |
| `PUT /admin/types/{key}` | Суперадмин | Изменить тип |
| `DELETE /admin/types/{key}` | Суперадмин | Удалить тип (встроенные удалить нельзя) |

Тело создания:

```json
{"title": "Справка о составе семьи", "keywords": ["справка о составе семьи"],
 "fields": [{"label": "Номер справки", "variants": ["Номер справки", "№"], "kind": "number", "required": true},
            {"label": "Дата выдачи", "kind": "date"}],
 "signature": true, "seal": true, "rule": "7.1", "rule_text": "…"}
```

`kind`: `text`, `name`, `date`, `number`.

## Живая камера

`POST /live/scan` — `multipart/form-data` с полем `frame` (JPEG до 4 МБ). Кадр распознаётся в быстром режиме и не сохраняется. Ответ:

```json
{"document_type": "academic_leave_application", "type_name": "Заявление на академический отпуск",
 "fields": {"student_name": "Козлова Анна Ивановна", "...": "..."}, "missing": ["course"],
 "regions": [{"field": "student_name", "kind": null, "quad": [[0.29, 0.50], [0.68, 0.50], [0.68, 0.54], [0.29, 0.55]]}],
 "sheet": [[0.23, 0.02], [0.53, 0.0], [0.55, 0.96], [0.24, 0.97]], "sheet_share": 0.31,
 "readable": true, "warnings": [], "seconds": 3.4}
```

Координаты нормированы к размеру кадра. `kind: "missing"` — место недостающей подписи или печати.

## Роли и профиль

| Запрос | Кто | Действие |
| --- | --- | --- |
| `GET/POST/DELETE /me/marks/signature` | Все | Своя подпись (PNG до 2 МБ) |
| `GET/POST/DELETE /me/marks/seal` | Сотрудник | Печать деканата |
| `POST /admin/invites` `{"note": "…"}` | Суперадмин | Одноразовая ссылка регистрации сотрудника, действует 7 дней |
| `DELETE /admin/invites/{prefix}` | Суперадмин | Отозвать приглашение |
| `GET /admin/users`, `PATCH /admin/users/{id}` `{"role": "staff"}` | Суперадмин | Пользователи и роли |

## Чат

`POST /documents/{slug}/chat` с телом `{"question": "Сколько длилась практика?"}`. Вопрос — до 2000 символов. Документ должен иметь статус `done`.

По умолчанию ответ приходит потоком `application/x-ndjson`:

```text
{"type": "kind", "kind": "computed", "label": "Вычислено по документу"}
{"type": "delta", "text": "Практика длилась "}
{"type": "delta", "text": "105 дней (с 1 января 2032 г. по 14 апреля 2032 г.)."}
{"type": "final", "reply": {"kind": "computed", "answer": "Практика длилась 105 дней …", "fields": ["internship_start", "internship_end"], "rules": [], "followups": ["Какая дата начала практики?"], "engine": {...}}}
```

С `?stream=0` возвращается один JSON — содержимое `reply`:

```bash
curl -X POST "https://dekanat.karpovprod.ru/api/v1/documents/$SLUG/chat?stream=0" \
  -H "Authorization: Bearer $DK_KEY" -H "Content-Type: application/json" \
  -d '{"question": "Чего не хватает в документе?"}'
```

Поле `engine.type` показывает, кто ответил: языковая модель или `rules`, движок правил. Список значений `kind` — в [assistant.md](assistant.md#виды-ответа).

`DELETE /documents/{slug}/chat` — очистить историю чата.

## Аккаунт (для веб-интерфейса)

| Метод и путь | Тело | |
| --- | --- | --- |
| `POST /api/auth/register` | `{email, password, name}` | Пароль не короче 8 символов. Ставит cookie сессии |
| `POST /api/auth/login` | `{email, password}` | |
| `POST /api/auth/logout` | | |
| `POST /api/auth/password` | `{current, new}` | Завершает остальные сессии |
| `GET /api/me`, `PATCH /api/me` | `{auto_approve: true}` | Профиль и авто-подтверждение |
| `GET /api/keys`, `POST /api/keys` | `{name}` | Список ключей; создание (ключ возвращается один раз) |
| `DELETE /api/keys/{id}` | | Удалить ключ |

## Служебное

`GET /api/health`, без авторизации:

```json
{"status": "ok", "assistant": true, "model": "qwen3.5:4b", "reader": "gpu-agent"}
```

`reader` принимает значения:

- `gpu` — локальная видеокарта;
- `cpu` — локальный процессор;
- `gpu-agent` — подключён GPU-агент;
- `server-cpu` — агент офлайн, распознаёт процессор сервера.

## Лимиты

На публичном сервере (nginx):

- 10 запросов в секунду на `/api/`, всплеск до 40;
- 10 запросов в минуту на `/api/auth/`;
- тело запроса до 205 МБ (20 файлов по 10 МБ).

## Пример: загрузить и дождаться результата (Python)

```python
import time, requests

BASE = "https://dekanat.karpovprod.ru/api/v1"
H = {"Authorization": "Bearer dk_live_..."}

with open("spravka.pdf", "rb") as f:
    doc = requests.post(f"{BASE}/documents", headers=H, files={"files": f}).json()["documents"][0]

while (d := requests.get(f"{BASE}/documents/{doc['slug']}", headers=H).json())["status"] not in ("done", "failed"):
    time.sleep(1)

print(d["found"], "/", d["total"], d["analysis"]["validation"]["status"])
answer = requests.post(f"{BASE}/documents/{doc['slug']}/chat?stream=0", headers=H,
                       json={"question": "Чего не хватает?"}).json()
print(answer["answer"])
```
