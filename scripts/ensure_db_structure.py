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
    dialect = engine.dialect.name

    # 1) 社团表
    try:
        table_names = set(inspector.get_table_names())
    except Exception:
        table_names = set()

    if 'societies' not in table_names:
        if dialect == 'postgresql':
            create_societies_sql = """
            CREATE TABLE societies (
                id SERIAL PRIMARY KEY,
                name VARCHAR(128) NOT NULL UNIQUE,
                code VARCHAR(64) NOT NULL UNIQUE,
                description TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        else:
            create_societies_sql = """
            CREATE TABLE societies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(128) NOT NULL UNIQUE,
                code VARCHAR(64) NOT NULL UNIQUE,
                description TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """

        with engine.begin() as conn:
            conn.execute(text(create_societies_sql))
            conn.execute(text("INSERT INTO societies (name, code, description, is_active) VALUES ('默认社团', 'default', '系统默认社团', 1)"))
        app.logger.info('已创建 societies 表并初始化默认社团')

    # 2) 多社团关键字段
    alter_plans = [
        ('users', 'managed_society_id', 'INTEGER'),
        ('users', 'is_super_admin', 'BOOLEAN DEFAULT FALSE'),
        ('student_info', 'society_id', 'INTEGER'),
        ('activities', 'society_id', 'INTEGER'),
        ('points_history', 'society_id', 'INTEGER'),
        ('message', 'target_society_id', 'INTEGER'),
    ]

    for table_name, col_name, col_type in alter_plans:
        if _column_exists(inspector, table_name, col_name):
            continue
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"))
        app.logger.info(f'已补齐 {table_name}.{col_name} 字段')

    # 3) 保证至少有一个总管理员
    if _column_exists(inspector, 'users', 'is_super_admin'):
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE users
                SET is_super_admin = TRUE
                WHERE id = (
                    SELECT u.id FROM users u
                    JOIN roles r ON u.role_id = r.id
                    WHERE lower(r.name) = 'admin'
                    ORDER BY u.id ASC
                    LIMIT 1
                )
                AND NOT EXISTS (SELECT 1 FROM users WHERE is_super_admin = TRUE)
            """))
        app.logger.info('已校验总管理员默认值')

    if not _column_exists(inspector, 'activities', 'registration_start_time'):
        if dialect == 'postgresql':
            alter_sql = "ALTER TABLE activities ADD COLUMN registration_start_time TIMESTAMP"
        else:
            alter_sql = "ALTER TABLE activities ADD COLUMN registration_start_time DATETIME"

        with engine.begin() as conn:
            conn.execute(text(alter_sql))

        app.logger.info('已补齐 activities.registration_start_time 字段')
    else:
        app.logger.info('字段 activities.registration_start_time 已存在，跳过补齐')
