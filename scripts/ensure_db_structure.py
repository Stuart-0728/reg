from sqlalchemy import inspect, text, bindparam


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

    # 1.1) 学生-社团多选关系表
    if 'student_societies' not in table_names:
        if dialect == 'postgresql':
            create_student_societies_sql = """
            CREATE TABLE student_societies (
                student_id INTEGER NOT NULL,
                society_id INTEGER NOT NULL,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (student_id, society_id),
                FOREIGN KEY (student_id) REFERENCES student_info(id) ON DELETE CASCADE,
                FOREIGN KEY (society_id) REFERENCES societies(id) ON DELETE CASCADE
            )
            """
        else:
            create_student_societies_sql = """
            CREATE TABLE student_societies (
                student_id INTEGER NOT NULL,
                society_id INTEGER NOT NULL,
                joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (student_id, society_id),
                FOREIGN KEY (student_id) REFERENCES student_info(id) ON DELETE CASCADE,
                FOREIGN KEY (society_id) REFERENCES societies(id) ON DELETE CASCADE
            )
            """

        with engine.begin() as conn:
            conn.execute(text(create_student_societies_sql))
        app.logger.info('已创建 student_societies 表')

    # 2) 多社团关键字段
    alter_plans = [
        ('users', 'managed_society_id', 'INTEGER'),
        ('users', 'is_super_admin', 'BOOLEAN DEFAULT FALSE'),
        ('users', 'wx_openid', 'VARCHAR(100) UNIQUE'),
        ('users', 'register_source', "VARCHAR(32) DEFAULT 'website'"),
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

    # 2.1) 从 student_info.society_id 回填到 student_societies（幂等）
    try:
        with engine.begin() as conn:
            if dialect == 'postgresql':
                conn.execute(text("""
                    INSERT INTO student_societies (student_id, society_id)
                    SELECT id, society_id
                    FROM student_info
                    WHERE society_id IS NOT NULL
                    ON CONFLICT (student_id, society_id) DO NOTHING
                """))
            else:
                conn.execute(text("""
                    INSERT OR IGNORE INTO student_societies (student_id, society_id)
                    SELECT id, society_id
                    FROM student_info
                    WHERE society_id IS NOT NULL
                """))
        app.logger.info('已同步 student_info.society_id 到 student_societies')
    except Exception as e:
        app.logger.warning(f'同步 student_societies 失败: {e}')

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

    if not _column_exists(inspector, 'activities', 'registration_success_message'):
        if dialect == 'postgresql':
            alter_sql = "ALTER TABLE activities ADD COLUMN registration_success_message TEXT"
        else:
            alter_sql = "ALTER TABLE activities ADD COLUMN registration_success_message TEXT"

        with engine.begin() as conn:
            conn.execute(text(alter_sql))

        app.logger.info('已补齐 activities.registration_success_message 字段')
    else:
        app.logger.info('字段 activities.registration_success_message 已存在，跳过补齐')

    # 团队报名相关字段
    if not _column_exists(inspector, 'activities', 'registration_mode'):
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE activities ADD COLUMN registration_mode VARCHAR(20) DEFAULT 'individual'"))
        app.logger.info('已补齐 activities.registration_mode 字段')
    else:
        app.logger.info('字段 activities.registration_mode 已存在，跳过补齐')

    if not _column_exists(inspector, 'activities', 'team_max_members'):
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE activities ADD COLUMN team_max_members INTEGER DEFAULT 1"))
        app.logger.info('已补齐 activities.team_max_members 字段')
    else:
        app.logger.info('字段 activities.team_max_members 已存在，跳过补齐')

    if not _column_exists(inspector, 'activities', 'team_max_count'):
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE activities ADD COLUMN team_max_count INTEGER DEFAULT 0"))
        app.logger.info('已补齐 activities.team_max_count 字段')
    else:
        app.logger.info('字段 activities.team_max_count 已存在，跳过补齐')

    if not _column_exists(inspector, 'registrations', 'team_id'):
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE registrations ADD COLUMN team_id INTEGER"))
        app.logger.info('已补齐 registrations.team_id 字段')
    else:
        app.logger.info('字段 registrations.team_id 已存在，跳过补齐')

    # 团队表
    if 'activity_teams' not in table_names:
        if dialect == 'postgresql':
            create_activity_teams_sql = """
            CREATE TABLE activity_teams (
                id SERIAL PRIMARY KEY,
                activity_id INTEGER NOT NULL,
                leader_user_id INTEGER NOT NULL,
                name VARCHAR(120) NOT NULL,
                team_code VARCHAR(24) NOT NULL UNIQUE,
                join_token VARCHAR(64) NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        else:
            create_activity_teams_sql = """
            CREATE TABLE activity_teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activity_id INTEGER NOT NULL,
                leader_user_id INTEGER NOT NULL,
                name VARCHAR(120) NOT NULL,
                team_code VARCHAR(24) NOT NULL UNIQUE,
                join_token VARCHAR(64) NOT NULL UNIQUE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """

        with engine.begin() as conn:
            conn.execute(text(create_activity_teams_sql))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_activity_team_activity_created ON activity_teams (activity_id, created_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_activity_team_activity_leader ON activity_teams (activity_id, leader_user_id)"))
        app.logger.info('已创建 activity_teams 表')

    if not _column_exists(inspector, 'notification_read', 'is_deleted'):
        if dialect == 'postgresql':
            alter_sql = "ALTER TABLE notification_read ADD COLUMN is_deleted BOOLEAN DEFAULT FALSE"
        else:
            alter_sql = "ALTER TABLE notification_read ADD COLUMN is_deleted BOOLEAN DEFAULT 0"

        with engine.begin() as conn:
            conn.execute(text(alter_sql))

        app.logger.info('已补齐 notification_read.is_deleted 字段')
    else:
        app.logger.info('字段 notification_read.is_deleted 已存在，跳过补齐')

    # 清理 notification_read 重复记录，避免同一用户同一通知出现多条状态冲突
    with engine.begin() as conn:
        duplicates = conn.execute(text("""
            SELECT user_id, notification_id, COUNT(*) AS cnt
            FROM notification_read
            GROUP BY user_id, notification_id
            HAVING COUNT(*) > 1
        """)).fetchall()

        removed_rows = 0
        for row in duplicates:
            user_id = row[0]
            notification_id = row[1]
            records = conn.execute(text("""
                SELECT id
                FROM notification_read
                WHERE user_id = :user_id AND notification_id = :notification_id
                ORDER BY
                    CASE WHEN is_deleted THEN 1 ELSE 0 END DESC,
                    CASE WHEN read_at IS NOT NULL THEN 1 ELSE 0 END DESC,
                    COALESCE(read_at, CURRENT_TIMESTAMP) DESC,
                    id DESC
            """), {
                'user_id': user_id,
                'notification_id': notification_id
            }).fetchall()

            if len(records) <= 1:
                continue

            keep_id = records[0][0]
            delete_ids = [r[0] for r in records[1:] if r[0] != keep_id]
            if delete_ids:
                conn.execute(
                    text("DELETE FROM notification_read WHERE id IN :ids").bindparams(bindparam("ids", expanding=True)),
                    {"ids": delete_ids}
                )
                removed_rows += len(delete_ids)

        if removed_rows:
            app.logger.info(f'已清理 notification_read 重复记录 {removed_rows} 条')
        else:
            app.logger.info('notification_read 无重复记录，跳过去重')

    # 4) 每日天气缓存表（降低第三方API消耗并稳定详情页加载）
    if 'weather_daily_cache' not in table_names:
        if dialect == 'postgresql':
            create_weather_cache_sql = """
            CREATE TABLE weather_daily_cache (
                id SERIAL PRIMARY KEY,
                city_adcode VARCHAR(16) NOT NULL,
                weather_date DATE NOT NULL,
                extensions VARCHAR(16) NOT NULL DEFAULT 'base',
                payload TEXT NOT NULL,
                source VARCHAR(32) DEFAULT 'unknown',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_weather_daily_cache_city_date_ext UNIQUE (city_adcode, weather_date, extensions)
            )
            """
        else:
            create_weather_cache_sql = """
            CREATE TABLE weather_daily_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                city_adcode VARCHAR(16) NOT NULL,
                weather_date DATE NOT NULL,
                extensions VARCHAR(16) NOT NULL DEFAULT 'base',
                payload TEXT NOT NULL,
                source VARCHAR(32) DEFAULT 'unknown',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_weather_daily_cache_city_date_ext UNIQUE (city_adcode, weather_date, extensions)
            )
            """

        with engine.begin() as conn:
            conn.execute(text(create_weather_cache_sql))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_weather_daily_cache_city_date ON weather_daily_cache (city_adcode, weather_date)"))
        app.logger.info('已创建 weather_daily_cache 表')
