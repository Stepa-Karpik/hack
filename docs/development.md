# Разработка

## Окружения

В проекте три независимых Python-окружения. Их нельзя устанавливать одно поверх другого: версии transformers в них разные.

| Файл | Для чего |
| --- | --- |
| `requirements-app.txt` | **Текущее приложение:** PaddleOCR-VL, веб-сервер, GPU-агент, тесты. Transformers 5.5.4 |
| `scripts/unified/requirements-paddle.txt` | Обучение и оценка PaddleOCR-VL (то же ядро плюс `lm-format-enforcer`) |
| `scripts/unified/requirements.txt` | Исследование Qwen2-VL / Qwen3-VL: Transformers 4.57, bitsandbytes |
| `requirements.txt`, `requirements.lock.txt` | Прежнее поколение: EasyOCR, Ultralytics, scikit-learn, Streamlit |

Torch ставится первым, из официального индекса PyTorch под нужную версию CUDA или CPU.

## Тесты

```bash
python -m pytest -q          # 561 тест
python -m pytest -q tests/test_app.py tests/test_assistant.py
```

Модели в тестах заменены заглушками (`FakeReader`, подмена `ollama_chat`), поэтому GPU и веса не нужны. Покрыто:

- приложение: регистрация, сессии, загрузка, очередь, проверка `Origin`, смена типа, сверка, одобрение, авто-подтверждение, API-ключи;
- связь с GPU-агентом и переход на CPU;
- ассистент: контекст, вычисленные факты, проверка привязки, нормализация вида ответа, поток;
- граф-декодер, привязка полей, layout v1 и v2, проза;
- прежнее поколение целиком.

## Карта кода

### `scripts/app/` — приложение

| Файл | |
| --- | --- |
| `server.py` | Starlette: маршруты, авторизация, загрузка, чат, раздача интерфейса, CLI |
| `store.py` | SQLite: пользователи, сессии, ключи, документы |
| `processing.py` | Очередь с приоритетами и процесс-читатель |
| `pipeline.py` | Карточка документа из ответа модели; ссылки `/check/<id>` |
| `remote.py` | Брокер GPU-агента, удалённый читатель и чат |
| `agent.py` | GPU-агент |
| `calibrate_review.py` | Подбор порогов «Проверьте» (только оценка) |

### `scripts/unified/` — модель PaddleOCR-VL и исследование единой модели

| Группа | Файлы |
| --- | --- |
| Чтение | `native_worker.py` (процесс-читатель), `fast_decode.py` (граф-декодер), `run_ocr_eval.py`, `run_graphic_strict.py` |
| Привязка | `text_binding.py`, `literal_layout.py`, `prose_binding.py`, `field_regions.py`, `contract.py` |
| Головы | `graphic_head.py`, `train_graphic_head.py`, `train_mark_patches.py`, `select_mark_rules.py`, `eval_mark_patches.py` |
| Генераторы данных | `prepare_v2.py`, `prepare_literal_values.py`, `prepare_natural_pages.py`, `prepare_mark_pages.py`, `prepare_real_marks.py`, `prepare_camera.py`, `fetch_natural_sources.py` |
| Обучение LoRA | `train_literal_ocr.py`, `train_literal_fullpage.py`, `train_literal_fp32.py`, `train_literal_values_fp32.py`, `train_natural_v5.py` |
| Оценка | `grade_*.py`, `compare_kit_fields.py`, `qualify_fast_decode.py`, `literal_grade.py` |
| Qwen2-VL / Qwen3-VL | `model.py`, `run.py`, `prepare.py`, `loss.py`, `download.py` |
| Прежние страницы | `local_native_web.py`, `local_native_page.py` |

### `scripts/assistant/` — ассистент

`core.py` (промпт, контекст, схема, проверка привязки), `http_chat.py` (поток), `eval_set.py`, `benchmark.py`, `regrade.py`, `eval_text.py`.

### `scripts/participantkit/` — контракт кейса

| Файл | |
| --- | --- |
| `format_v1.py` | Формат результата, проверка комплектности, ответы по правилам |
| `service.py`, `http_api.py`, `run_contract.py` | Сервис и HTTP прежнего поколения |
| `labeled_fields.py`, `crop_recovery.py`, `value_quote_recovery.py`, `mark_guard.py` | Доработки извлечения прежнего поколения |
| `upload_limits.py` | Проверка файла до загрузки модели: формат, мегапиксели, страницы |

### `dekanat/` — библиотека прежнего поколения

`ocr.py` (EasyOCR и каскад дообученных распознавателей), `preprocessing.py` (перспектива, наклон, свет), `orientation.py`, `extraction.py`, `narrative.py`, `slots.py`, `field_validation.py`, `pdf_text*.py` (текстовый слой PDF), `visual.py` (YOLO и MobileNet), `schema.py`, `reasoning.py`, `synthetic.py`.

### `scripts/*.py` — обучение, оценка и утилиты прежнего поколения

`train_ocr.py`, `train_quote_ocr.py`, `train_detection.py`, `train_visual.py`, `train_fields.py`, `generate_data.py`, `evaluate*.py`, `check_document.py` (CLI одного документа), `serve_api.py` (HTTP web-v1), `build_web.py`.

## Соглашения

- **Эталоны не попадают в инференс.** Скрипты чтения не открывают файлы ответов; оценка выполняется отдельными `grade_*`. Об этом говорят docstring модулей.
- **Результаты неизменяемы.** Каждый запуск пишет в новую папку и отказывается перезаписывать существующие выходы (`Fresh output required`).
- **Без выдумок.** Ни один этап не дописывает значение, которого нет в прочитанном тексте. Сомнительное помечается, отсутствующее остаётся «не найдено».
- **Внешний код не выполняется.** Модели загружаются с `trust_remote_code=False` по зафиксированным ревизиям с проверкой SHA-256.
- **Попарная проверка.** Новая версия модели или правила включается только после сравнения с текущей на тех же входах: без потерь ранее верных значений. Методика — в [evaluation.md](evaluation.md).

## Как добавить тип документа

1. **Правила.** В `configs/participant_v1.json` добавить тип в `requirements`: группы обязательных ключей с номерами пунктов. Текст пунктов добавить в `rules`.
2. **Привязка.** В `scripts/participantkit/format_v1.py` добавить подписи новых полей в `LABELS`. В `scripts/unified/text_binding.py` добавить заголовок документа в `TITLES`.
3. **Интерфейс.** Добавить названия типа и полей в `web-app/assets/js/ui.js` (`TYPES`, `LABELS`), в `scripts/assistant/core.py` (`TYPE_NAMES`, `FIELD_NAMES`) и в `TYPES` сервера.
4. **Проверка.** Сгенерировать несколько страниц нового типа и проверить привязку. Если модель путает характерные значения, дообучить адаптер на новых страницах (см. [training.md](training.md)).

Распознавание при этом не меняется: модель читает весь текст страницы независимо от типа.
