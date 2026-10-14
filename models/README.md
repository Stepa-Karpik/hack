# Модели

Все модели в этом каталоге обучены в рамках проекта. Базовые модели (PaddleOCR-VL 1.6, Qwen2-VL-2B, Qwen3-VL-2B) и стандартные веса EasyOCR и YOLO сюда не входят: они скачиваются из официальных источников. У каждой модели есть свой `README.md` с параметрами и лицензиями.

## Текущее приложение

| Каталог | Что это | Основа | Размер |
| --- | --- | --- | --- |
| [`unified-experimental-natural-v5`](unified-experimental-natural-v5) | **LoRA v5** языковой части: чтение русских документов | PaddleOCR-VL 1.6 | 2,5 МБ |
| [`unified-experimental-graphic-head-fp32-v3`](unified-experimental-graphic-head-fp32-v3) | **Глобальная графическая голова** (подпись, печать), 41 474 параметра | PaddleOCR-VL 1.6, замороженный vision | 0,4 МБ |
| [`unified-experimental-mark-patches-v1`](unified-experimental-mark-patches-v1) | **Патч-голова**: подпись и печать с рамками, порог в `thresholds.json` | PaddleOCR-VL 1.6, замороженный vision | 1,2 МБ |

Базовая модель:

```bash
python deploy/app-v2/fetch_base_model.py deploy/app-v2/base-model-manifest.json work/paddle-vl-base-v1
```

## Предыдущие версии PaddleOCR-VL

| Каталог | Что это | Итог |
| --- | --- | --- |
| `unified-experimental-literal-values-fp32-v4` | LoRA v4: значения полей трёх схем, FP32 | 277/280 и 276/280; основа для v5 |
| `unified-experimental-literal-fp32-v3` | LoRA v3: первые FP32-страницы | Без потерь, CER 70 → 44 |
| `unified-experimental-literal-fullpage-v2` | LoRA при 2 Мп, BF16 (точки 40, 80) | Отклонена: 2 Мп хуже |
| `unified-experimental-literal-ocr-v1` | Первая языковая LoRA (точки 40, 80, 120) | Отклонена: потеря верного значения |
| `unified-experimental-graphic-head-v1`, `-v2` | Графические головы в BF16 | Заменены v3 |
| `unified-experimental-paddle-v3` | Сквозной JSON, совместная LoRA | Отклонена: 18/56 |
| `unified-experimental-paddle-binding-v4` | Сквозной JSON с весами loss | Отклонена: 25/56 |

## Исследование Qwen2-VL / Qwen3-VL

| Каталог | Основа | Что это |
| --- | --- | --- |
| `unified-experimental-decoder` | Qwen2-VL-2B | QLoRA языковой части, пилот |
| `unified-experimental-vision` | Qwen2-VL-2B | Совместная LoRA vision + language |
| `unified-experimental-expanded-v2` | Qwen2-VL-2B | Расширенный корпус |
| `unified-experimental-semantic-v3` | Qwen2-VL-2B | Балансировка loss |
| `unified-experimental-qwen3-v1` | Qwen3-VL-2B | Языковая LoRA |
| `unified-experimental-qwen3-joint-v2` | Qwen3-VL-2B | Совместная LoRA |
| `unified-experimental-camera-v3` | Qwen3-VL-2B | Продолжение на «снимках камерой» |

Все эти модели отклонены. Почему — в [docs/research.md](../docs/research.md).

## Прежнее поколение (web-v1)

| Файл | Что это |
| --- | --- |
| `ocr_cyrillic.pt` | EasyOCR `cyrillic_g2`, дообученный на числовых полях. Используется каскадом |
| `ocr_run01.pt` | Первый запуск того же дообучения |
| `ocr_selection.json` | Решение о включении каскада, привязанное к SHA весов |
| `ocr_quotes.pt`, `quote_selection.json` | Распознаватель с токенами «» для названий в кавычках |
| `marks.pt` | YOLOv8n: подпись и печать |
| `visual.pt`, `visual.last.pt` | MobileNetV3 Small по нижней зоне страницы (резерв) |
| `fields.joblib` | Классификатор меток полей (scikit-learn) |

Стандартные веса EasyOCR (`craft_mlt_25k.pth`, `cyrillic_g2.pth`) скачиваются библиотекой EasyOCR при первом запуске.

## Лицензии

- Собственные модели — AGPL-3.0: при обучении детектора прежнего поколения и голов использованы подписи Ultralytics (AGPL-3.0).
- Базовые модели PaddleOCR-VL и Qwen — Apache-2.0. Их лицензии и карточки лежат рядом с адаптерами (`BASE-LICENSE`, `BASE_MODEL_CARD.md`).
