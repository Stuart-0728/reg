import re

with open('src/templates/main/index.html', 'r', encoding='utf-8') as f:
    text = f.read()

text = re.sub(r'\s*<button class="carousel-control-prev".*?</button>\s*<button class="carousel-control-next".*?</button>\s*</div>\s*', '\n\n', text, flags=re.DOTALL)

with open('src/templates/main/index.html', 'w', encoding='utf-8') as f:
    f.write(text)
