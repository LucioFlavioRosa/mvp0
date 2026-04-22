# app/core/database.py
import os
import uuid
import urllib.parse
import pyodbc
import time
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.core.config import Settings

# Instância global de Settings
settings = Settings()

# Configurações do banco (Busca no ambiente ou no Key Vault)
DB_SERVER = settings.get_secret("DB_SERVER")
DB_NAME = settings.get_secret("DB_NAME")
DB_USER = settings.get_secret("DB_USER")
DB_PASSWORD = settings.get_secret("DB_PASSWORD")

# ============================================================================
# 1. SQLAlchemy (Novo - Usado pelo BFF/Portal)
# ============================================================================

class Base(DeclarativeBase):
    def to_dict(self):
        unloaded = inspect(self).unloaded
        return {
            c.name: str(getattr(self, c.name)) if isinstance(getattr(self, c.name), uuid.UUID) else getattr(self, c.name)
            for c in self.__table__.columns
            if c.name not in unloaded
        }

engine = None
SessionLocal = None

if DB_SERVER and DB_NAME and DB_USER and DB_PASSWORD:
    try:
        connection_string = (
            f"DRIVER={{ODBC Driver 18 for SQL Server}};"
            f"SERVER={DB_SERVER};DATABASE={DB_NAME};"
            f"UID={DB_USER};PWD={DB_PASSWORD};TrustServerCertificate=yes;"
            f"Timeout=120;"
        )
        # Engine para SQLAlchemy
        engine = create_engine(
            f"mssql+pyodbc:///?odbc_connect={urllib.parse.quote_plus(connection_string)}",
            connect_args={"timeout": 120}
        )
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        print("[OK] SQLAlchemy: Conexão configurada.")
    except Exception as e:
        print(f"[ERRO] SQLAlchemy: Falha ao configurar: {e}")

def get_db():
    if not SessionLocal:
        yield None
        return
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ============================================================================
# 2. DatabaseManager (Legado - Usado pelo Chatbot/BotEngine)
# ============================================================================

class DatabaseManager:
    """
    Mantém a compatibilidade com o Chatbot existente.
    Utiliza chamadas diretas via pyodbc com suporte a retry.
    """
    def __init__(self):
        self.conn_str = (
            f"DRIVER={{ODBC Driver 18 for SQL Server}};"
            f"SERVER={DB_SERVER};DATABASE={DB_NAME};"
            f"UID={DB_USER};PWD={DB_PASSWORD};TrustServerCertificate=yes;"
            f"Timeout=120;"
        )

    def _get_connection(self):
        return pyodbc.connect(self.conn_str)

    def _execute_with_retry(self, op, query, params=None, retries=3):
        for i in range(retries):
            conn = None
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                result = op(cursor, query, params)
                conn.commit()
                return result
            except (pyodbc.Error, Exception) as e:
                print(f"[RETRY {i+1}/{retries}] Erro no banco: {e}")
                if i == retries - 1:
                    raise e
                time.sleep(2 ** i)
            finally:
                if conn:
                    try:
                        conn.close()
                    except:
                        pass
        return None

    def _read_one_op(self, cursor, query, params):
        cursor.execute(query, params or ())
        return cursor.fetchone()

    def _write_op(self, cursor, query, params):
        cursor.execute(query, params or ())
        return True

    def _read_all_op(self, cursor, query, params):
        cursor.execute(query, params or ())
        return cursor.fetchall()

    def execute_read_one(self, query, params=None):
        return self._execute_with_retry(self._read_one_op, query, params)

    def execute_read_all(self, query, params=None):
        return self._execute_with_retry(self._read_all_op, query, params)

    def execute_write(self, query, params=None):
        result = self._execute_with_retry(self._write_op, query, params)
        return result is True

    def execute_transaction(self, queries_with_params):
        """Executa múltiplas queries em uma única transação"""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            for query, params in queries_with_params:
                cursor.execute(query, params or ())
            conn.commit()
            return True
        except Exception as e:
            print(f"[ERRO] Transação falhou: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                conn.close()
