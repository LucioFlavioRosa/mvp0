import os
from dotenv import load_dotenv
load_dotenv()

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from threading import Lock

class Settings:
    """
    Centraliza leitura de secrets do Azure Key Vault.
    Utiliza cache local para evitar chamadas repetidas.
    """
    _instance = None
    _lock = Lock()

    def __new__(cls):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(Settings, cls).__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self):
        self._secrets_cache = {}
        self._cache_lock = Lock()
        self.keyvault_url = os.environ.get('AZURE_KEYVAULT_URL')
        
        if not self.keyvault_url:
            print("[INFO] AZURE_KEYVAULT_URL nao detectada. O sistema funcionara apenas com variaveis de ambiente (OS).")
            self.client = None
            return

        try:
            self.credential = DefaultAzureCredential()
            self.client = SecretClient(vault_url=self.keyvault_url, credential=self.credential)
            print(f"[OK] Conectado ao Key Vault: {self.keyvault_url}")
        except Exception as e:
            print(f"[AVISO] Falha ao inicializar Key Vault: {e}. O sistema usara fallback para variaveis de ambiente.")
            self.client = None

    def get_secret(self, secret_name: str):
        """
        Busca o secret na seguinte ordem:
        1. Variáveis de ambiente (ex: App Service)
        2. Cache local (evita chamadas repetidas)
        3. Azure Key Vault
        """
        # 1. Tenta Variável de Ambiente (Normalizada: hifen vira underline)
        env_name = secret_name.replace("-", "_").upper()
        env_value = os.environ.get(env_name) or os.environ.get(secret_name)
        if env_value:
            return env_value

        # 2. Busca no cache local
        with self._cache_lock:
            if secret_name in self._secrets_cache:
                return self._secrets_cache[secret_name]

        # 3. Busca no Key Vault
        try:
            # Se não houver URL do Key Vault, apenas retornamos None ou erro
            if not self.keyvault_url:
                return None

            secret = self.client.get_secret(secret_name)
            value = secret.value
            with self._cache_lock:
                self._secrets_cache[secret_name] = value
            return value
        except Exception as e:
            # Se o secret não existir no ambiente nem no KV, logamos o aviso
            # mas permitimos o fluxo continuar para variáveis não críticas
            print(f"[AVISO] Secret '{secret_name}' nao encontrado no ambiente nem no KV: {e}")
            return None

    def get_all_secrets(self, secret_names):
        """
        Busca múltiplos secrets e retorna dict.
        """
        result = {}
        for name in secret_names:
            result[name] = self.get_secret(name)
        return result