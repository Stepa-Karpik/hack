# Развёртывание app-v2 (dekanat.karpovprod.ru)

Развёрнуто 14 октября 2026 года.

## Схема

- **Сервер** (без GPU). Служба `online-dekanat-app` работает на 127.0.0.1:18780 за nginx. На ней аккаунты, история, API и база.
  - Код: `/opt/online-dekanat/releases/app-v2`.
  - Окружение: `/opt/online-dekanat/venv-app` (torch CPU).
  - Базовая модель: `/opt/online-dekanat/models/paddle-vl-1.6`. Она скачана с Hugging Face по зафиксированной ревизии и сверена по sha256 с `base-model-manifest.json`.
  - Данные: `/opt/online-dekanat/app-state` (SQLite, файлы, `agent-token`).
- **GPU-агент** на компьютере владельца: `launch-agent.ps1`.
  - Сам подключается к `wss://dekanat.karpovprod.ru/agent/ws`, входящие порты не нужны.
  - Распознаёт документы на своём GPU и отвечает в чате через локальную Ollama.
  - Токен лежит в `work\agent-v1\agent-token` в корне проекта.
- **Если агент не подключён:**
  - распознавание идёт на CPU сервера, 1–3 минуты, без подсветки текстовых полей;
  - чат работает в режиме правил.

  `/api/health` показывает текущий режим в поле `reader`: `gpu-agent` или `server-cpu`.

## Обновление

1. Собрать архив: `python deploy/app-v2/build_release.py app-v2.tar.gz`.
2. Загрузить его в `/tmp/` на сервере.
3. Выполнить `bash install.sh /tmp/app-v2.tar.gz release`, затем `bash install.sh /tmp/app-v2.tar.gz service`. Прежний релиз переименовывается в `app-v2.prev-*`.

Этапы: `release venv model service nginx switch`.

## Откат на web-v1

1. Вернуть конфиги nginx из `/opt/online-dekanat/nginx-backup/` (`site-*.conf` → `/etc/nginx/sites-available/online-dekanat`, `limits-*.conf` → `/etc/nginx/conf.d/online-dekanat-limits.conf`).
2. Выполнить `nginx -t && systemctl reload nginx`.
3. Выполнить `systemctl enable --now online-dekanat`.
