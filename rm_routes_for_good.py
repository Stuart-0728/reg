import re

with open('src/routes/admin.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Completely rip out system_logs and backup routing functions to kill the memory leaks

# Find @admin_bp.route('/system_logs' and cut until next route
code = re.sub(r"@admin_bp.route\('/system_logs', methods=\['GET'\]\).*?def system_logs\(\):.*?(?=@admin_bp.route|$)", "", code, flags=re.DOTALL)

# Find backup endpoint
code = re.sub(r"@admin_bp.route\('/backup', methods=\['GET', 'POST'\]\).*?def backup\(\):.*?(?=@admin_bp.route|$)", "", code, flags=re.DOTALL)

with open('src/routes/admin.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("Killed system logs and backup endpoints to prevent memory leaks")
