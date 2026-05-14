import pyodbc
import time
import random
from app.core.config import Settings
from app.core.telemetry import get_logger
from app.core import log_dimensions as ld

logger = get_logger(__name__)


class DatabaseManager:
    def __init__(self):
        try:
            settings = Settings()
            self.conn_str = (
                f"DRIVER={{ODBC Driver 18 for SQL Server}};"
                f"SERVER={settings.get_secret('DB-SERVER')};"
                f"DATABASE={settings.get_secret('DB-NAME')};"
                f"UID={settings.get_secret('DB-USER')};"
                f"PWD={settings.get_secret('DB-PASSWORD')};"
                "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=60;LoginTimeout=60;"
            )
        except Exception:
            logger.critical("falha ao configurar secrets do banco", exc_info=True,
                            extra={"custom_dimensions": {
                                ld.OPERATION: "startup", ld.COMPONENT: "database",
                            }})
            self.conn_str = ""

    def _get_connection(self):
        return pyodbc.connect(self.conn_str)

    def _execute_with_retry(self, operation_func, query, params=None):
        max_retries = 6
        base_delay = 2

        for attempt in range(max_retries):
            conn = None
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                result = operation_func(cursor, query, params)
                # Qualquer op de write (_write_op, _write_rowcount_op, ...) precisa commit
                if operation_func.__name__.startswith('_write'):
                    conn.commit()
                return result

            except pyodbc.Error as e:
                error_msg = str(e)
                is_transient_error = any(
                    code in error_msg
                    for code in ['08001', 'HYT00', '08S01', '10054', 'TCP Provider']
                )

                if is_transient_error and attempt < max_retries - 1:
                    sleep_time = (base_delay * (2 ** attempt)) + random.uniform(0, 1)
                    logger.warning("banco transient error, fazendo retry",
                                   extra={"custom_dimensions": {
                                       ld.OPERATION: "db_query",
                                       "attempt": attempt + 1,
                                       "max_retries": max_retries,
                                       "sleep_seconds": round(sleep_time, 2),
                                   }})
                    logger.debug("aguardando antes do retry",
                                 extra={"custom_dimensions": {"sleep_seconds": round(sleep_time, 2)}})
                    time.sleep(sleep_time)
                    continue

                logger.error("erro fatal no banco", exc_info=True,
                             extra={"custom_dimensions": {
                                 ld.OPERATION: "db_query",
                                 "attempt": attempt + 1,
                             }})
                return None

            except Exception:
                logger.error("erro generico no banco", exc_info=True,
                             extra={"custom_dimensions": {ld.OPERATION: "db_query"}})
                return None

            finally:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass

        return None

    def _read_one_op(self, cursor, query, params):
        cursor.execute(query, params or ())
        return cursor.fetchone()

    def _write_op(self, cursor, query, params):
        cursor.execute(query, params or ())
        return True

    def _write_rowcount_op(self, cursor, query, params):
        """Variante do _write_op que retorna cursor.rowcount em vez de True.

        Necessario para optimistic locking: o caller precisa saber se a UPDATE
        afetou 1 linha (sucesso) ou 0 linhas (conflito de versao detectado).
        """
        cursor.execute(query, params or ())
        # pyodbc retorna -1 quando rowcount nao esta disponivel; nesse caso
        # tratamos como sucesso (best-effort).
        rc = cursor.rowcount
        return rc if rc is not None else -1

    def execute_read_one(self, query, params=None):
        return self._execute_with_retry(self._read_one_op, query, params)

    def execute_write(self, query, params=None):
        result = self._execute_with_retry(self._write_op, query, params)
        return result is True

    def execute_write_with_rowcount(self, query, params=None):
        """Executa write e retorna rowcount (rows affected).

        Returns:
            int: numero de linhas afetadas (>=0), ou -1 se driver nao
                 reporta rowcount, ou None em caso de erro fatal apos retries.
        """
        return self._execute_with_retry(self._write_rowcount_op, query, params)

    def execute_transaction(self, queries_with_params):
        conn = None
        try:
            for i in range(4):
                try:
                    conn = self._get_connection()
                    break
                except Exception:
                    if i < 3:
                        time.sleep(5)

            if not conn:
                return False

            cursor = conn.cursor()
            for query, params in queries_with_params:
                cursor.execute(query, params or ())
            conn.commit()
            return True
        except Exception:
            if conn:
                conn.rollback()
            logger.error("erro em transacao", exc_info=True,
                         extra={"custom_dimensions": {ld.OPERATION: "db_transaction"}})
            return False
        finally:
            if conn:
                conn.close()
