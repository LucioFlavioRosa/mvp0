import pyodbc
import time
import random
from app.core.config import Settings

class DatabaseManager:
    def __init__(self):
        try:
            settings = Settings()
            self.conn_str = (
                f"DRIVER={{ODBC Driver 18 for SQL Server}};"
                f"SERVER={settings.get_secret('DB_SERVER')};"
                f"DATABASE={settings.get_secret('DB_NAME')};"
                f"UID={settings.get_secret('DB_USER')};"
                f"PWD={settings.get_secret('DB_PASSWORD')};"
                "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=60;LoginTimeout=60;"
            )
        except Exception as e:
            print(f"⚠️ AVISO: Falha ao configurar secrets do Banco: {e}")
            self.conn_str = ""

    def _get_connection(self):
        return pyodbc.connect(self.conn_str)

    def _execute_with_retry(self, operation_func, query, params=None):
        """
        Mecanismo central de imunidade.
        Tenta executar uma função (leitura ou escrita) várias vezes.
        """
        max_retries = 6
        base_delay = 2   
        
        for attempt in range(max_retries):
            conn = None
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                
                result = operation_func(cursor, query, params)
                
                if operation_func.__name__ == '_write_op':
                    conn.commit()
                
                return result

            except pyodbc.Error as e:
                error_msg = str(e)
                is_transient_error = any(code in error_msg for code in ['08001', 'HYT00', '08S01', '10054', 'TCP Provider'])
                
                if is_transient_error:
                    if attempt < max_retries - 1:
                       
                        sleep_time = (base_delay * (2 ** attempt)) + random.uniform(0, 1)
                        
                        print(f"💤 [DB] Banco dormindo ou falha de rede. Tentativa {attempt+1}/{max_retries}.")
                        print(f"⏳ Aguardando {sleep_time:.2f}s para acordar o Azure...")
                        time.sleep(sleep_time)
                        continue 
                
                print(f"🔥 Erro Fatal no Banco (Tentativa {attempt+1}): {e}")
                return None
                
            except Exception as e:
                print(f"🔥 Erro Genérico: {e}")
                return None
                
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

    def execute_read_one(self, query, params=None):
        return self._execute_with_retry(self._read_one_op, query, params)

    def execute_write(self, query, params=None):
        result = self._execute_with_retry(self._write_op, query, params)
        return result is True

    def execute_transaction(self, queries_with_params):
        conn = None
        try:
            # Retry manual simplificado para conexão inicial da transação
            for i in range(4): # Tenta por uns ~15 segundos
                try:
                    conn = self._get_connection()
                    break
                except:
                    if i < 3: time.sleep(5)
            
            if not conn: return False

            cursor = conn.cursor()
            for query, params in queries_with_params:
                cursor.execute(query, params or ())
            conn.commit()
            return True
        except Exception as e:
            if conn: conn.rollback()
            print(f"🔥 Erro Transação: {e}")
            return False
        finally:
            if conn: conn.close()