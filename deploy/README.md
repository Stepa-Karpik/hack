# Конфигурации развёртывания

| Каталог / файл | Что это |
| --- | --- |
| [`app-v2/`](app-v2/README.md) | Текущее развёртывание: приложение на сервере и GPU-агент на компьютере с видеокартой. Скрипт установки, systemd, nginx, сборка релиза |
| `online-dekanat.service`, `nginx-site.conf`, `nginx-limits.conf` | Прежний релиз web-v1 (EasyOCR + YOLO, `scripts/serve_api.py`). Сохранены для отката |
| `certificate-renewal-hook.sh` | Перезагрузка nginx после продления сертификата Let's Encrypt |
| `server-requirements.lock.txt` | Точные версии CPU-окружения web-v1 |

## Прежний релиз web-v1

1. Python 3.12 venv. Сначала CPU torch: `pip install torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cpu`.
2. Затем `requirements.txt` и явно `scikit-learn==1.9.1 joblib==1.6.0 ultralytics==8.4.175`. Системные пакеты Ubuntu: `python3.12-venv libgl1`.
3. Код релиза доступен службе только на чтение. Изменяемые данные лежат в отдельном каталоге `state`. Веса EasyOCR копируются в `state/easyocr`.
4. systemd unit `online-dekanat`: 4 CPU, 4 GiB, один worker. Проверка: `/health` на loopback и один настоящий документ.
5. Сначала HTTP-конфигурация для ACME и получение сертификата certbot, затем HTTPS-vhost. Перед перезагрузкой nginx — `nginx -t`.
