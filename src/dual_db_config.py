import os


class DualDbConfig:
    """Minimal dual-db config provider used by admin/db_sync modules.

    This fallback implementation keeps API compatibility and avoids import
    failures when dual-db is not configured.
    """

    def __init__(self):
        self.primary_db_url = (
            os.environ.get('PRIMARY_DATABASE_URL')
            or os.environ.get('DATABASE_URL')
            or os.environ.get('SQLALCHEMY_DATABASE_URI')
            or ''
        )
        self.backup_db_url = os.environ.get('BACKUP_DATABASE_URL') or ''

    def is_dual_db_enabled(self):
        return bool(self.primary_db_url and self.backup_db_url)

    def get_database_info(self):
        return {
            'dual_db_enabled': self.is_dual_db_enabled(),
            'primary_configured': bool(self.primary_db_url),
            'backup_configured': bool(self.backup_db_url),
            'primary_db_url': self._mask_url(self.primary_db_url),
            'backup_db_url': self._mask_url(self.backup_db_url),
        }

    @staticmethod
    def _mask_url(url):
        if not url:
            return ''
        # Hide credentials if present: scheme://user:pass@host -> scheme://***:***@host
        at_idx = url.find('@')
        scheme_idx = url.find('://')
        if at_idx > 0 and scheme_idx >= 0:
            prefix = url[:scheme_idx + 3]
            suffix = url[at_idx + 1:]
            return prefix + '***:***@' + suffix
        return url


dual_db = DualDbConfig()
