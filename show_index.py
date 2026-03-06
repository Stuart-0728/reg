with open('src/templates/main/index.html', 'r', encoding='utf-8') as f:
    for i, l in enumerate(f.readlines()[:100]):
        print(f"{i}: {l.strip()}")
