import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))  # DON'T CHANGE THIS !!!

import logging
import argparse
from src import create_app

# 导入自动备份服务
try:
    from src.auto_backup import start_auto_backup_thread
    AUTO_BACKUP_AVAILABLE = True
except ImportError as e:
    print(f"自动备份功能不可用: {e}")
    AUTO_BACKUP_AVAILABLE = False

# 获取当前文件目录的绝对路径
current_dir = os.path.dirname(os.path.abspath(__file__))
# 设置日志文件的绝对路径
log_file_path = os.path.join(current_dir, 'logs', 'cqnu_association.log')

# 确保日志目录存在
os.makedirs(os.path.dirname(log_file_path), exist_ok=True)

# 设置日志记录
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                   handlers=[
                       logging.FileHandler(os.path.join(current_dir, 'logs', 'cqnu_association.log')),
                       logging.StreamHandler()
                   ])

logger = logging.getLogger(__name__)

if __name__ == '__main__':
    # 创建命令行参数解析器
    parser = argparse.ArgumentParser(description='启动CQNU智能社团+管理系统')
    parser.add_argument('--port', type=int, default=8082, help='服务器端口号(默认: 8082)')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='服务器主机地址(默认: 0.0.0.0)')
    args = parser.parse_args()
    
    # 使用命令行参数设置端口
    port = args.port
    host = args.host
    
    print(f"启动服务器: {host}:{port}")
    app = create_app()

    # 启动自动备份服务
    if AUTO_BACKUP_AVAILABLE:
        try:
            backup_service = start_auto_backup_thread()
            logger.info("自动备份服务已启动（每6小时备份一次）")
        except Exception as e:
            logger.error(f"启动自动备份服务失败: {e}")
    else:
        logger.warning("自动备份服务不可用")

    app.run(host=host, port=port)
