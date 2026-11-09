import sys
from pathlib import Path

from string import Template

page = Path(sys.argv[1]).read_text()
print(Template(page).substitute(title="Plural", year=YEAR))
