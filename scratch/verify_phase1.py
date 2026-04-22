import sys
import os

# Adiciona o caminho do projeto ao sys.path
sys.path.append(os.getcwd())

try:
    print("Iniciando validação de imports da Fase 1...")
    
    print("1. Testando import de app.core.config...")
    from app.core.config import Settings
    settings = Settings()
    print("   [OK] Settings carregado.")
    
    print("2. Testando import de app.core.database...")
    from app.core.database import Base, engine, get_db
    print("   [OK] Base, engine e get_db carregados.")
    
    print("3. Testando import de app.models...")
    import app.models
    print("   [OK] Models carregados com sucesso.")
    
    print("\n[V] Validacao concluida: Todos os componentes da Fase 1 foram migrados e estao conversando corretamente!")

except Exception as e:
    print(f"\n[X] ERRO na validacao: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
