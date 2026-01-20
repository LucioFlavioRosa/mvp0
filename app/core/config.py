import os
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
            raise RuntimeError("AZURE_KEYVAULT_URL não definida no ambiente.")
        try:
            self.credential = DefaultAzureCredential()
            self.client = SecretClient(vault_url=self.keyvault_url, credential=self.credential)
        except Exception as e:
            raise RuntimeError(f"Erro ao inicializar acesso ao Key Vault: {e}")

    def get_secret(self, secret_name):
        """
        Busca o secret no cache local, se não existir busca no Key Vault.
        """
        with self._cache_lock:
            if secret_name in self._secrets_cache:
                return self._secrets_cache[secret_name]
        try:
            secret = self.client.get_secret(secret_name)
            value = secret.value
            with self._cache_lock:
                self._secrets_cache[secret_name] = value
            return value
        except Exception as e:
            raise RuntimeError(f"Erro ao buscar secret '{secret_name}' no Key Vault: {e}")

    def get_all_secrets(self, secret_names):
        """
        Busca múltiplos secrets e retorna dict.
        """
        result = {}
        for name in secret_names:
            result[name] = self.get_secret(name)
        return result