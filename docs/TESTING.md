# Testes — Bot Águas do Pará

> Documentação da suite de testes unitários do projeto. Para arquitetura geral ver [`ARCHITECTURE.md`](ARCHITECTURE.md), para deploy ver [`DEPLOYMENT.md`](DEPLOYMENT.md).

## Visão geral

A suite hoje tem **71 testes unitários** distribuídos em 9 arquivos. Cobertura global em **44%**, com cobertura cirúrgica nos caminhos críticos: autenticação, retry transient, DLQ, dispatch.

| Métrica | Valor |
|---|---|
| Total de testes | 71 |
| Tempo de execução (suite completa) | ~1s |
| Não-flaky em 3+ rodadas consecutivas | OK |
| Sem dependência externa (rede, disco, DB real) | OK |
| Cobertura total | 44% |
| Arquivos com 100% de cobertura | `dispatch_service.py`, `schemas/dlq.py`, `schemas/infobip_webhook.py`, `core/log_dimensions.py` |

## Filosofia

A suite **não mira em coverage % cego**. Mira em **caminhos críticos cobertos** — autenticação, retry policy, DLQ semantics, dispatch contract — onde a falta de teste mais doeria em incidente. Esses são os P0 e P1 documentados na skill `python-testing-bootstrap`.

Cada teste passa pelos princípios:

- **Pega bug real**: nome do teste descreve o comportamento esperado; se a regra de negócio mudar, o teste falha
- **Sem `time.sleep`**: testes não esperam por relógio
- **Sem rede / disco / DB real**: tudo mockado via fixtures (`mock_settings`, `mock_db`, `mock_infobip`, `mock_dlq`) ou via `requests-mock`
- **Sem dependência de ordem**: cada teste roda isolado
- **AAA (Arrange, Act, Assert)**: estrutura clara, falha indica problema específico

## Como rodar

### Pré-requisitos

```bash
pip install -r requirements-dev.txt
```

Dependências (em `requirements-dev.txt`):

- `pytest>=8.0` + `pytest-cov` + `pytest-mock` + `pytest-asyncio`
- `requests-mock>=1.12` (intercepta HTTP outbound)
- `httpx>=0.27` (necessário pelo TestClient do FastAPI)

### Comandos comuns

```bash
# Roda toda a suite
pytest tests/

# Só um arquivo
pytest tests/unit/test_admin_auth.py -v

# Só um teste
pytest tests/unit/test_admin_auth.py::test_admin_dlq_returns_401_with_wrong_user -v

# Com cobertura no terminal
pytest tests/ --cov=app --cov=main --cov-report=term-missing

# HTML report (abre htmlcov/index.html)
pytest tests/ --cov=app --cov=main --cov-report=html

# Modo verbose + parar no primeiro falha
pytest tests/ -v -x

# Anti-flaky check (roda 3x)
for i in 1 2 3; do pytest tests/ --no-cov 2>&1 | tail -2; done
```

### CI

Workflow `.github/workflows/tests.yml` roda em todo PR e push para `main`:

- Instala `unixodbc` (necessário para o import de `pyodbc` no `app/core/database.py`)
- Instala `requirements.txt` + `requirements-dev.txt`
- Roda `pytest tests/ --cov=app --cov=main --cov-report=term-missing --cov-report=xml -v`
- Salva `coverage.xml` como artifact

## Inventário dos arquivos de teste

### `tests/unit/test_sanity.py` (3 testes)

Sanity da infraestrutura. Garante que o conftest carrega, `TestClient` instancia, e `FakeSettings` funciona. Tipicamente o primeiro a quebrar se algum import ou fixture base regride.

### `tests/unit/test_admin_auth.py` (12 testes)

`verify_admin_basic_auth` + endpoints `/admin/dlq` e `/admin/dlq/retry/{id}`.

Cobre: happy path (fila vazia / com mensagens), 401 (sem header / user errado / password errado), 503 fail-safe (`ADMIN-USER` ou `ADMIN-PASSWORD` ausentes), borda do `limit` (clampa entre 1 e 32), 404 quando mensagem não existe, política "delete obrigatório após retry".

### `tests/unit/test_webhook_auth.py` (7 testes)

`verify_infobip_basic_auth` + `POST /bot`.

Cobre: happy path, 401, 503 fail-safe (`INFOBIP-WEBHOOK-USER`/`PASSWORD` ausentes), 422 (Pydantic rejeita payload sem `results`).

### `tests/unit/test_infobip_client.py` (8 testes)

`InfobipClient` (retry transient + DLQ enqueue).

Cobre: `send_text`/`send_template` happy path + Authorization header correto, política 4xx (sem retry, enfileira DLQ), política 5xx transient (retry 2x e sucesso), 5xx persistente (retry esgota + DLQ), `Timeout`, `ConnectionError`, contrato do `DLQMessage` enfileirado (path/body completos pra admin reconstruir).

> **Detalhe**: NÃO usa a fixture `mock_infobip` (que mocka a classe inteira). Aqui queremos o `InfobipClient` REAL para testar a lógica de `_dispatch` e `@transient_retry`. Usa `requests-mock` interceptando HTTP no nível da URL.

### `tests/unit/test_dispatch_service.py` (5 testes)

`DispatchService.enviar_oferta_para_prestadores`.

Cobre: happy 2 parceiros, pedido inexistente (sem envio), parceiro inexistente (pula, continua), `INSERT` falha (pula esse), placeholders na ordem `[nome, atividade, numero, rua, bairro, data, obs, valor, urgencia]` — defesa contra refactor que troque a ordem do template `oferta_servico`.

> **Detalhe técnico**: usa `DispatchService.__new__` + injeção direta de `self.db`/`self.whatsapp` em vez de patch da classe. Razão: `dispatch_service.py` faz `from app.core.database import DatabaseManager` e `from app.services.whatsapp_service import WhatsAppService` no topo — o cache do nome no namespace local quebra `mocker.patch` normal.

### `tests/unit/test_schemas.py` (9 testes)

Schemas Pydantic do projeto.

Cobre: `DLQMessage` (constraint `attempts>=1`, campos obrigatórios, `sender_hash` opcional, `model_dump_json` produz JSON parseável); `InfobipInboundPayload` (aliases `from`→`sender` / `messageCount`→`message_count`, discriminator `TEXT` vs `IMAGE`, `results` obrigatório).

### `tests/unit/test_telemetry_utils.py` (8 testes)

`mask_pii`, `get_logger`, `get_operation_id` de `app/core/telemetry.py`.

Cobre: `mask_pii` determinismo (LGPD depende disso pra correlação Kusto), hash 12 chars hex, inputs diferentes geram hashs diferentes (sanity), tratamento de `None`/`""` ⇒ `"<empty>"`, rotação de `LOG_PII_SALT` invalida hashs antigos.

### `tests/unit/test_dlq_client.py` (10 testes)

`DLQClient` real (não a fixture `mock_dlq`).

Cobre: `enqueue` happy + 2 cenários fail-safe (queue offline / `send_message` levanta); `peek` (vazio / com dados parseados / clampa entre 1 e 32); `receive_by_id` (não encontra → `None` / encontra → atualiza `pop_receipt` via `update_message` — defesa contra `pop receipt mismatch`); `delete` happy + retorno `False` sem propagar quando `delete_message` levanta.

> **Detalhe**: mocka `QueueClient.from_connection_string` (Azure Storage Queue) para não conectar real.

### `tests/unit/test_bot_engine_transitions.py` (9 testes)

`BotEngine._get_session`, `_save_session` e `processar_mensagem`.

Cobre: sessão nova (`START`), sessão ativa (step + dados), timeout 5 min (`START` + `step_backup`), passos terminais (sem `step_backup`), `_save_session` skipa `START`/`NO_UPDATE` e grava demais, oferta pendente intercepta fluxo de cadastro, saudação no meio do fluxo grava `step_backup`.

> **Detalhe técnico**: usa `BotEngine.__new__` + injeção de atributos. Razão: `__init__` é pesado (instancia 7 módulos de etapa, alguns com Google Maps client no construtor).

## Fixtures globais (`tests/conftest.py`)

Todas as fixtures abaixo são reusáveis em qualquer teste do projeto.

### `env_vars` (autouse)

Aplicada automaticamente em todos os testes. Define env vars mínimas (`AZURE_KEYVAULT_URL`, `LOG_LEVEL`, `LOG_PII_SALT`) e remove `APPLICATIONINSIGHTS_CONNECTION_STRING` para evitar telemetria real.

### `mock_settings`

Substitui `Settings` por `FakeSettings` com defaults para todos os 14 secrets do projeto. Suporta `.set()` para sobrescrever:

```python
def test_X(mock_settings):
    mock_settings.set("ADMIN-USER", "custom")
    mock_settings.set("ADMIN-PASSWORD", None)  # simula secret ausente
```

### `mock_db`

`DatabaseManager` mockado. Defaults: `execute_read_one` retorna `None`, `execute_write` retorna `True`. Override:

```python
def test_X(mock_db):
    mock_db.execute_read_one.return_value = ("uuid", "Nome")
    mock_db.execute_read_one.side_effect = [linha1, linha2, None]  # sequencial
```

### `mock_infobip`

Mocka a CLASSE `InfobipClient`. Para testar a lógica REAL do `InfobipClient` (retry, DLQ), **não use esta fixture** — instancie `InfobipClient(...)` direto e use `requests-mock` (ver `test_infobip_client.py`).

### `mock_dlq`

Mocka a CLASSE `DLQClient`. Mesma observação: para testar `DLQClient` real (`enqueue`, `peek`, `receive_by_id`, `delete`), instancie direto e mocke `QueueClient.from_connection_string` (ver `test_dlq_client.py`).

### `client`

`TestClient` do FastAPI com `main.app` carregado e todos os mocks acima aplicados. Usado para testar endpoints (`GET /admin/dlq`, `POST /bot`, etc).

```python
def test_X(client):
    response = client.get("/admin/dlq", auth=("admin-user", "admin-pass"))
    assert response.status_code == 200
```

## Padrões de mocking

### HTTP outbound (Infobip, ViaCEP, Google Maps)

Sempre `requests-mock` — intercepta no nível da URL, sobrevive a refactors do código HTTP interno:

```python
def test_send_text_happy(infobip_client, requests_mock):
    requests_mock.post(
        "https://fake.api.infobip.com/whatsapp/1/message/text",
        json={"messages": [...]},
        status_code=200,
    )
    result = infobip_client.send_text(sender="5511", to="5522", text="oi")
```

Sequência de respostas (para testar retry):

```python
requests_mock.post(URL, [
    {"status_code": 500, "json": {"error": "transient"}},
    {"status_code": 200, "json": {"messages": []}},
])
```

### DB queries

`mock_db.execute_read_one.side_effect` quando o teste chama múltiplas queries:

```python
mock_db.execute_read_one.side_effect = [
    PEDIDO_ROW,              # 1ª chamada: SELECT pedido
    ("5511", "Joao"),        # 2ª: SELECT parceiro 1
    None,                    # 3ª: parceiro 2 não encontrado
]
```

### Classes pesadas (__init__ com I/O)

`__new__` + injeção direta de atributos. Pattern usado em `test_dispatch_service.py` e `test_bot_engine_transitions.py`:

```python
service = DispatchService.__new__(DispatchService)
service.db = MagicMock()
service.whatsapp = MagicMock()
service.TEMPLATE_OFERTA = "oferta_servico"
```

### Stub de dependência nativa (`pyodbc`)

`tests/__init__.py` aplica `sys.modules.setdefault("pyodbc", MagicMock())` **antes** de qualquer import do projeto. Necessário porque `pyodbc` precisa de `libodbc.so.2` no sistema, que não está no GitHub Actions runner por default.

## Cobertura

Estado atual (após PR `test/cover-resilience-p1`):

| Módulo | Cobertura |
|---|---|
| `app/services/dispatch_service.py` | **100%** |
| `app/schemas/dlq.py` | **100%** |
| `app/schemas/infobip_webhook.py` | **100%** |
| `app/core/log_dimensions.py` | **100%** |
| `app/integrations/infobip.py` | 86% |
| `app/core/telemetry.py` | 80% |
| `app/core/retry.py` | 76% |
| `app/integrations/dlq.py` | 76% |
| `main.py` | 53% |
| `app/services/azure_blob_service.py` | 40% |
| `app/bot_engine.py` | 38% |
| `app/modules/etapa_veiculos.py` | 38% |
| `app/services/whatsapp_service.py` | 33% |
| `app/modules/onboarding.py` | 31% |
| `app/modules/etapa_habilidades.py` | 31% |
| `app/modules/etapa_disponibilidade.py` | 30% |
| `app/modules/etapa_endereco.py` | 28% |
| `app/services/session_service.py` | 27% |
| `app/core/config.py` | 26% |
| `app/core/database.py` | 19% |
| `app/modules/etapa_pessoal.py` | 19% |
| `app/modules/etapa_oferta.py` | 17% |
| `app/modules/etapa_documentos.py` | 15% |
| **TOTAL** | **44%** |

### Gaps conhecidos (não cobertos)

- **Módulos de etapa** (`etapa_pessoal`, `etapa_endereco`, `etapa_habilidades`, `etapa_veiculos`, `etapa_disponibilidade`, `etapa_documentos`, `etapa_oferta`) — caminhos de cada `processar_*` específico, integrações com ViaCEP/Google Maps, persistência inline. Cobertura via testes de `BotEngine` end-to-end seria custosa; cobertura por etapa individual quando tocarmos cada uma em PR.
- **`app/core/database.py`** — caminho de retry exponencial em cold start do Azure SQL Serverless. Testar exige mock de `pyodbc.OperationalError` com códigos `08001`/`HYT00`/`08S01`/`10054`. Vale fazer quando houver incidente nesse caminho.
- **`app/core/config.py`** — leitura real do Key Vault via `DefaultAzureCredential`. Não testamos (depende de credenciais Azure). `FakeSettings` no conftest cobre o contrato.
- **`app/services/whatsapp_service.py`** — `_processar_sequencia` com threading + `time.sleep`. Mockar threading inline é frágil; refactor para `asyncio` (já no roadmap) facilitará cobrir.

## Adicionando um teste novo

A skill `python-testing-bootstrap` automatiza o fluxo. Resumo manual:

1. **Identificar o alvo** — arquivo, função, classe, ou endpoint
2. **Classificar pelo tipo** (catálogo em [skill `references/test-types.md`](../.claude/skills/python-testing-bootstrap/references/test-types.md) se a skill estiver instalada):
   - Endpoint FastAPI com auth → 6 casos canônicos
   - Cliente HTTP externo → 6 casos
   - Service com DB → 5 casos
   - Schema Pydantic → 5 casos
   - Função pura → 4-5 casos (parametrize agressivamente)
   - State machine → 1 teste por transição crítica
3. **Plan** — listar casos antes de escrever, evita testar coisa que não importa
4. **Implementar** seguindo AAA (Arrange, Act, Assert) + nomes descritivos
5. **Self-review** — pytest passa, não-flaky em 3 rodadas, coverage do alvo cobre os casos do plano
6. **Commit** — branch `test/cover-<alvo>`, 1 alvo por PR

### Naming convention

| Padrão | Exemplo |
|---|---|
| Arquivo | `tests/unit/test_<modulo>.py` |
| Função | `test_<alvo>_<comportamento_esperado>` |
| Branch | `test/cover-<alvo>` |

Bom: `test_admin_dlq_returns_503_when_admin_user_missing`
Ruim: `test_admin_dlq_1`, `test_negative_case`

## Troubleshooting

### `ImportError: libodbc.so.2: cannot open shared object file`

`pyodbc` precisa de `unixodbc` instalado no sistema. CI já faz `apt-get install` (passo "Install ODBC system dependency"). Dev local: instalar `unixodbc` via pacote do sistema, OU confiar no stub em `tests/__init__.py` (suficiente pra testes unitários).

### `StopIteration` em `mock_db.execute_read_one`

Acontece quando `side_effect=[lista]` é exaurido antes do esperado. Causa comum: cache de import deixa `self.db` apontando pro mock do teste anterior. Solução: usar `__new__` + injeção direta (ver `test_dispatch_service.py`).

### Teste passa isolado mas falha quando rodado com outros

State leak via `sys.modules`. Geralmente é `from X import Y` no topo do módulo testado, que cacheia a referência no primeiro import. Soluções:

- `mocker.patch.object(module, "Name")` em vez de `mocker.patch("module.Name")`
- `importlib.reload(module)` no início do teste/fixture
- `__new__` + injeção direta (mais robusto)

### Coverage não aparece para um módulo

Confirma que o módulo é **importado** durante algum teste. Coverage só observa código que rodou. Módulos puramente declarativos (constantes, classes nunca instanciadas) ficam em 0% mesmo que estejam corretos.

### CI vermelho com "no tests collected"

pytest retorna exit code 5 quando não acha testes. Se isso acontece pós-refactor, conferir:

- Arquivos seguem padrão `test_*.py`
- Funções seguem padrão `test_*`
- `pytest.ini` `testpaths = tests` aponta pra pasta certa
- Cache `__pycache__/` desatualizado — `find . -name __pycache__ -exec rm -rf {} +`

## Skill de apoio

A skill **[`python-testing-bootstrap`](https://github.com/.../skills)** automatiza:

- Detecção de pytest configurado / bootstrap se ausente
- Identificação do alvo + plano de casos (com aprovação do user)
- Geração dos testes seguindo padrões deste documento
- Self-review (pytest + cobertura + não-flaky)

Para invocar: descrever o alvo, ex.: *"escreve testes pra `verify_admin_basic_auth`"*, *"cobre o `DispatchService`"*, *"adiciona testes nos endpoints `/admin/dlq*`"*.
