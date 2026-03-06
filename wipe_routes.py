import re
with open('src/routes/admin.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Try to remove endpoints completely
text = re.sub(r"@admin_bp.route\('/backup'.*?def backup\(\):.*?return render_template\('admin/backup.html'.*?\)", "", text, flags=re.DOTALL)
text = re.sub(r"@admin_bp.route\('/system-logs'.*?def system_logs\(\):.*?return render_template\('admin/system_logs.html'.*?\)", "", text, flags=re.DOTALL)

with open('src/routes/admin.py', 'w', encoding='utf-8') as f:
    f.write(text)
