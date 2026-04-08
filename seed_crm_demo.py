#!/usr/bin/env python3
"""
Заполняет три сущности CRM (клиенты → сделки → задачи) через HTTP API случайными,
но правдоподобными данными (~по COUNT записей в каждую таблицу).

Запуск (из корня проекта; сначала в другом терминале: python crm/crm.py):
  python seed_crm_demo.py
  python seed_crm_demo.py --base-url http://127.0.0.1:8080 --count 1000

Без --base-url скрипт сам ищет ответ на /health: CRM_API_BASE_URL, затем порты 8000 и 8080.

Переменные окружения:
  CRM_API_BASE_URL — приоритетный URL API, если не задан --base-url
  CRM_SEED_COUNT — число записей на каждую таблицу (по умолчанию 1000)

Если на сервере включена синхронизация Google Sheets на каждый POST, массовая загрузка
будет очень медленной. Для ускорения запустите API с CRM_GOOGLE_SYNC=0 в .env.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from datetime import datetime, timedelta, timezone

import requests


def _health_ok(session: requests.Session, base: str) -> bool:
    try:
        r = session.get(f"{base.rstrip('/')}/health", timeout=3)
        return 200 <= r.status_code < 300
    except requests.RequestException:
        return False


def resolve_api_base(session: requests.Session, explicit_base: str) -> str | None:
    """
    Если явно передан --base-url — проверяется только он.
    Иначе: CRM_API_BASE_URL, затем 127.0.0.1:8000 и :8080 (как у GUI/Docker).
    """
    explicit = (explicit_base or "").strip()
    if explicit:
        b = explicit.rstrip("/")
        if _health_ok(session, b):
            return b
        print(f"Указанный --base-url недоступен: {b}/health", file=sys.stderr)
        return None

    candidates: list[str] = []
    env = os.environ.get("CRM_API_BASE_URL", "").strip()
    if env:
        candidates.append(env.rstrip("/"))
    for port in (8000, 8080):
        candidates.append(f"http://127.0.0.1:{port}")
        candidates.append(f"http://localhost:{port}")

    seen: set[str] = set()
    for base in candidates:
        b = base.rstrip("/")
        if b in seen:
            continue
        seen.add(b)
        if _health_ok(session, b):
            return b
    return None


FIRST_NAMES = (
    "Александр",
    "Дмитрий",
    "Максим",
    "Сергей",
    "Андрей",
    "Алексей",
    "Артём",
    "Илья",
    "Кирилл",
    "Михаил",
    "Елена",
    "Ольга",
    "Татьяна",
    "Наталья",
    "Ирина",
    "Светлана",
    "Мария",
    "Анна",
    "Екатерина",
    "Юлия",
    "Алёна",
    "Дарья",
    "Полина",
    "Виктория",
    "Софья",
)

LAST_NAMES = (
    "Иванов",
    "Смирнов",
    "Кузнецов",
    "Попов",
    "Соколов",
    "Лебедев",
    "Морозов",
    "Новиков",
    "Фёдоров",
    "Волков",
    "Морозова",
    "Орлова",
    "Соколова",
    "Кузнецова",
    "Лебедева",
    "Новикова",
    "Егорова",
    "Петрова",
    "Волкова",
    "Козлова",
    "Соколов",
    "Васильев",
    "Зайцев",
    "Павлов",
    "Семёнов",
)

COMPANY_PREFIXES = ("ООО", "ИП", "АО", "ПАО")
COMPANY_SUBJECTS = (
    "ТехноСервис",
    "СтройМаркет",
    "Логистика",
    "ПромСнаб",
    "ИнфоСистемы",
    "МедиаГрупп",
    "АгроПродукт",
    "ТоргСеть",
    "УмныйДом",
    "ЭкоПак",
    "ФинАналитик",
    "КадрПро",
    "НордТрейд",
    "ВолгаСбыт",
    "РегионСервис",
)

DEAL_STATUSES = ("lead", "negotiation", "won", "lost", "order_placed")
CURRENCIES = ("RUB", "RUB", "RUB", "USD", "EUR")

DEAL_TITLES = (
    "Поставка оборудования",
    "Лицензия ПО на год",
    "Разработка интеграции",
    "Сопровождение и поддержка",
    "Пилотный проект",
    "Расширение лицензии",
    "Аудит и консалтинг",
    "Обучение персонала",
    "Внедрение CRM",
    "Модернизация серверов",
)

TASK_VERBS = (
    "Позвонить",
    "Отправить КП",
    "Согласовать договор",
    "Напомнить об оплате",
    "Подготовить отчёт",
    "Согласовать с юристом",
    "Запланировать встречу",
    "Отправить счёт",
    "Уточнить ТЗ",
    "Проверить оплату",
)


def _rand_phone() -> str:
    return "+79" + f"{random.randint(0, 999_999_999):09d}"


def _rand_email(local: str) -> str:
    dom = random.choice(("mail.ru", "yandex.ru", "gmail.com", "company.ru"))
    safe = "".join(c if c.isalnum() else "_" for c in local.lower())[:40]
    return f"{safe}_{random.randint(1, 9999)}@{dom}"


def _rand_due() -> str:
    delta = timedelta(days=random.randint(-30, 120), hours=random.randint(0, 23))
    dt = datetime.now(timezone.utc) + delta
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="Заполнение CRM тестовыми данными через API.")
    parser.add_argument(
        "--base-url",
        default="",
        help="Базовый URL API. Если не указан, перебираются CRM_API_BASE_URL и порты 8000/8080.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=int(os.environ.get("CRM_SEED_COUNT", "1000")),
        help="Сколько записей создать в каждой из трёх таблиц (по умолчанию 1000)",
    )
    args = parser.parse_args()
    n = max(1, min(args.count, 100_000))

    session = requests.Session()
    session.headers["Accept"] = "application/json"

    base = resolve_api_base(session, args.base_url)
    if not base:
        print(
            "Не удалось связаться с API (/health). Запустите сервер в отдельном терминале:\n"
            "  python crm/crm.py\n"
            "или укажите URL: --base-url http://127.0.0.1:8080",
            file=sys.stderr,
        )
        return 1
    print(f"API: {base}")

    random.seed()

    print(f"Создание {n} клиентов…")
    client_ids: list[int] = []
    for i in range(n):
        fn, ln = random.choice(FIRST_NAMES), random.choice(LAST_NAMES)
        name = f"{fn} {ln}"
        company = f'{random.choice(COMPANY_PREFIXES)} «{random.choice(COMPANY_SUBJECTS)}»'
        body = {
            "name": name,
            "email": _rand_email(f"{fn}.{ln}"),
            "phone": _rand_phone(),
            "company": company,
            "notes": random.choice(
                (
                    "Предпочитает связь по почте",
                    "Запросил демо на следующей неделе",
                    "Работает по НДС",
                    "Нужен договор с типовой формой",
                    "",
                )
            ),
            "status": random.choices(["active", "archived"], weights=[9, 1], k=1)[0],
        }
        try:
            resp = session.post(f"{base}/clients", json=body, timeout=120)
            resp.raise_for_status()
            cid = resp.json()["id"]
            client_ids.append(cid)
        except requests.RequestException as e:
            print(f"Ошибка POST /clients на шаге {i + 1}: {e}", file=sys.stderr)
            if hasattr(e, "response") and e.response is not None:
                print(e.response.text, file=sys.stderr)
            return 1
        if (i + 1) % 200 == 0:
            print(f"  … клиентов: {i + 1}/{n}")

    print(f"Создание {n} сделок…")
    deal_ids: list[int] = []
    for i in range(n):
        cid = random.choice(client_ids) if client_ids and random.random() > 0.05 else None
        amt = round(random.uniform(15_000, 4_500_000), 2)
        body = {
            "client_id": cid,
            "title": f"{random.choice(DEAL_TITLES)} — {random.choice(COMPANY_SUBJECTS)}",
            "description": random.choice(
                (
                    "Обсудили условия поставки, ждём подпись.",
                    "Требуется согласование с финансами.",
                    "Перенос сроков по просьбе клиента.",
                    "",
                )
            ),
            "amount": amt,
            "currency": random.choice(CURRENCIES),
            "status": random.choice(DEAL_STATUSES),
            "order_number": f"ORD-{datetime.now().year}-{random.randint(10000, 99999)}",
        }
        try:
            resp = session.post(f"{base}/deals", json=body, timeout=120)
            resp.raise_for_status()
            deal_ids.append(resp.json()["id"])
        except requests.RequestException as e:
            print(f"Ошибка POST /deals на шаге {i + 1}: {e}", file=sys.stderr)
            if hasattr(e, "response") and e.response is not None:
                print(e.response.text, file=sys.stderr)
            return 1
        if (i + 1) % 200 == 0:
            print(f"  … сделок: {i + 1}/{n}")

    print(f"Создание {n} задач…")
    for i in range(n):
        cid = random.choice(client_ids) if client_ids and random.random() > 0.08 else None
        did = random.choice(deal_ids) if deal_ids and random.random() > 0.12 else None
        body = {
            "client_id": cid,
            "deal_id": did,
            "title": f"{random.choice(TASK_VERBS)}: {random.choice(DEAL_TITLES).lower()}",
            "description": random.choice(
                (
                    "Срок — до конца недели.",
                    "Клиент ждёт обратной связи.",
                    "",
                )
            ),
            "due_at": _rand_due() if random.random() > 0.15 else None,
            "completed": random.random() < 0.22,
        }
        try:
            resp = session.post(f"{base}/tasks", json=body, timeout=120)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"Ошибка POST /tasks на шаге {i + 1}: {e}", file=sys.stderr)
            if hasattr(e, "response") and e.response is not None:
                print(e.response.text, file=sys.stderr)
            return 1
        if (i + 1) % 200 == 0:
            print(f"  … задач: {i + 1}/{n}")

    print("Готово.")
    print(f"  Клиентов: {n}, сделок: {n}, задач: {n}.")
    print("  В Google Sheets (если настроено) соответствуют листы CRM_Clients / CRM_Deals / CRM_Tasks")
    print("  или имена из CRM_GOOGLE_TAB_* в .env.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
