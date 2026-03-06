import os
import glob

def replace_in_folder(folder_path, old_text, new_text):
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            if file.endswith('.html') or file.endswith('.py') or file.endswith('.js') or file.endswith('.md'):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    if old_text in content:
                        content = content.replace(old_text, new_text)
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(content)
                        print(f"Updated: {file_path}")
                except Exception as e:
                    pass

replace_in_folder('./src', '师能素质协会', '智能社团+')
