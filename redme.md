Переделаем под твои названия. Настроим два PostgreSQL-контейнера в Podman с физической репликацией и последующим переключением Primary.

Важный нюанс: при физической репликации второй сервер получит копию первого, поэтому внутри обоих контейнеров будет база ai_mentor. База ai_mentor_2 может существовать дополнительно, но Python должен подключаться к одной и той же базе ai_mentor на обоих хостах.

1. Конфигурация контейнеров

Параметр	Primary	Standby
Container name	ai-mentor-db	ai-mentor-db-2
PostgreSQL user	ai_mentor	ai_mentor
Password	ai_mentor	ai_mentor
Database для Python	ai_mentor	ai_mentor
Дополнительная БД	—	ai_mentor_2 (по желанию)
Port mapping	5432:5432	5433:5432

2. Создаём Primary

Если контейнеры с такими именами уже существуют, сначала сохрани нужные данные. Следующие команды рассчитаны на чистое тестовое окружение.

Создаём сеть:

podman network create ai-mentor-net

Создаём первый контейнер:

podman run -d \
  --name ai-mentor-db \
  --network ai-mentor-net \
  -p 5432:5432 \
  -e POSTGRES_USER=ai_mentor \
  -e POSTGRES_PASSWORD=ai_mentor \
  -e POSTGRES_DB=ai_mentor \
  docker.io/library/postgres:16 \
  -c wal_level=replica \
  -c max_wal_senders=10 \
  -c max_replication_slots=10 \
  -c listen_addresses='*'

Проверяем:

podman exec ai-mentor-db \
  psql -U ai_mentor -d ai_mentor \
  -c "SELECT pg_is_in_recovery();"

Ожидаем false.

3. Настраиваем репликацию

Создай пользователя для репликации:

podman exec ai-mentor-db \
  psql -U ai_mentor -d ai_mentor \
  -c "CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'replica123';"

Разреши подключения репликации:

podman exec -u postgres ai-mentor-db bash -c \
  "echo 'host replication replicator all scram-sha-256' >> /var/lib/postgresql/data/pg_hba.conf"

Применяем настройки:

podman exec ai-mentor-db \
  psql -U ai_mentor -d ai_mentor \
  -c "SELECT pg_reload_conf();"

4. Создаём Standby

Создай volume:

podman volume create ai-mentor-standby-data

Копируем данные Primary:

podman run --rm \
  --network ai-mentor-net \
  -v ai-mentor-standby-data:/var/lib/postgresql/data \
  -e PGPASSWORD=replica123 \
  --entrypoint bash \
  docker.io/library/postgres:16 \
  -c 'pg_basebackup \
    -h ai-mentor-db \
    -U replicator \
    -D /var/lib/postgresql/data \
    -Fp -Xs -P -R'

После завершения создаём второй контейнер:

podman run -d \
  --name ai-mentor-db-2 \
  --network ai-mentor-net \
  -p 5433:5432 \
  -v ai-mentor-standby-data:/var/lib/postgresql/data \
  docker.io/library/postgres:16

Проверяем состояние:

podman exec ai-mentor-db-2 \
  psql -U ai_mentor -d ai_mentor \
  -c "SELECT pg_is_in_recovery();"

Ожидаем true.

Если здесь появится ошибка прав доступа к каталогу данных, нужно будет отдельно настроить права Podman volume.

5. Настраиваем DBeaver

Создай два подключения:

Параметр	Первое	Второе
Host	localhost	localhost
Port	5432	5433
Database	ai_mentor	ai_mentor
Username	ai_mentor	ai_mentor
Password	ai_mentor	ai_mentor

На первом сервере:

CREATE TABLE failover_test (
    id BIGSERIAL PRIMARY KEY,
    message TEXT NOT NULL
);
INSERT INTO failover_test (message)
VALUES ('Hello from primary');

На втором:

SELECT * FROM failover_test;

Запись должна появиться автоматически.

6. Подключаем Python

Твой get_database_engine():

from functools import lru_cache
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
@lru_cache
def get_database_engine() -> AsyncEngine:
    url = URL.create(
        drivername="postgresql+asyncpg",
        username="ai_mentor",
        password="ai_mentor",
        database="ai_mentor",
        query={
            "host": (
                "localhost:5432",
                "localhost:5433",
            ),
        },
    )
    return create_async_engine(
        url,
        pool_size=10,
        max_overflow=20,
        pool_recycle=3600,
        pool_pre_ping=True,
        connect_args={
            "target_session_attrs": "read-write",
            "statement_cache_size": 0,
            "timeout": 3,
        },
    )
@lru_cache
def get_session_maker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=get_database_engine(),
        expire_on_commit=False,
    )

Твой сервис будет создавать новые соединения к доступному серверу, который принимает запись.

7. Проверяем переключение

Сначала запускаешь Python-сервис и проверяешь, что он подключается к Primary.

Затем останавливаешь первый контейнер:

podman stop ai-mentor-db

В DBeaver переключаешься на второе подключение (localhost:5433) и выполняешь:

SELECT pg_promote(wait => true);

Проверяешь:

SELECT pg_is_in_recovery();

Результат должен стать false.

Теперь новые соединения Python должны использовать второй сервер.

Итог: ты проверишь именно тот сценарий, который обсуждал с тимлидом: первый хост перестал быть доступным, второй стал Primary, а Python продолжил работу без перезапуска приложения.

Не запускай старый Primary обратно без процедуры повторного присоединения к кластеру: это может привести к расхождению данных.