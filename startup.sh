#!/bin/bash
set -e

# Exporta AZURE_KEYVAULT_URL se não estiver definida (ajuste conforme sua infra)
export AZURE_KEYVAULT_URL=${AZURE_KEYVAULT_URL:-"https://<SEU_KEYVAULT_NAME>.vault.azure.net/"}

# Instala dependências
pip install --upgrade pip
pip install -r requirements.txt

# Inicia o servidor FastAPI com Uvicorn
exec uvicorn main:app --host 0.0.0.0 --port 8000