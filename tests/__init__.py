"""Inicializacao do pacote tests.

IMPORTANTE: este __init__.py eh propositalmente NAO-vazio. Ele aplica stub
de pyodbc antes do conftest carregar.

Por que aqui e nao no conftest.py?
- conftest.py eh carregado por pytest APOS python descobrir o pacote tests.
- Para garantir que o stub de pyodbc roda ANTES de qualquer
  `mocker.patch("app.core.database.DatabaseManager")` (que importa o modulo,
  que importa pyodbc), o stub precisa vir no nivel de package init.

O stub eh defensivo: se o sistema tem libodbc.so.2 instalado (Linux com
unixodbc, ou Windows com ODBC Driver), `import pyodbc` funciona normalmente
e o stub nao eh usado. Se NAO tem (ex: GitHub Actions sem apt-get install),
o stub mantem `import pyodbc` funcional como MagicMock para os imports do
projeto nao explodirem durante coleta de teste.
"""

import sys
from unittest.mock import MagicMock

sys.modules.setdefault("pyodbc", MagicMock())
