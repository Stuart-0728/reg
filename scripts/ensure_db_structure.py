from sqlalchemy import inspect, text


def _column_exists(inspector, table_name, column_name):
    try:
        columns = inspector.get_columns(table_name)
        return any(col.get('name') == column_name for col in columns)
    except Exception:
        return False


def ensure_db_structure(app, db):
    """确保数据库关键结构存在（轻量级在线补齐）。"""
    engine = db.engine
    inspector = inspect(engine)

    if not _column_exists(inspector, 'activities', 'registration_start_time'):
        dialect = engine.dialect.name
        if dialect == 'postgresql':
            alter_sql = "ALTER TABLE activities ADD COLUMN registration_start_time TIMESTAMP"
        else:
            alter_sql = "ALTER TABLE activities ADD COLUMN registration_start_time DATETIME"

        with engine.begin() as conn:
            conn.execute(text(alter_sql))

        app.logger.info('已补齐 activities.registration_start_time 字段')
    else:
        app.logger.info('字段 activities.registration_start_time 已存在，跳过补齐')
