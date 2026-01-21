#!/bin/bash

# 1. Instalação do Driver ODBC 18 para SQL Server (Debian/Ubuntu)
# Isso é necessário para o pyodbc funcionar no Linux do Azure
curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add -
curl https://packages.microsoft.com/config/debian/11/prod.list > /etc/apt/sources.list.d/mssql-release.list

apt-get update
ACCEPT_EULA=Y apt-get install -y msodbcsql18
ACCEPT_EULA=Y apt-get install -y unixodbc-dev

# 2. Inicia a Aplicação
# Usa Gunicorn como gerenciador de processos e Uvicorn como worker
gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app
