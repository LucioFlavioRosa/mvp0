# Módulo: services

> Camada de aplicação entre o domínio (bot/modules) e o mundo externo (Infobip, Azure Blob, SQL).

## Propósito

Cada service encapsula uma capacidade externa ou um agregado de operações de domínio. O bot e os módulos de etapa nunca falam HTTP/SQL direto — sempre via service.

## Estrutura

| Arquivo | Classe principal | Responsabilidade |
|---|---|---|
| `whatsapp_service.py` | `WhatsAppService` | Envio outbound de mensagens via Infobip |
| `dispatch_service.py` | `DispatchService` | Notifica parceiros sobre novo pedido |
| `azure_blob_service.py` | `AzureBlobService` | Baixa mídia recebida no chat e sobe pro Blob |
| `parceiro_service.py` | `ParceiroService` | CRUD do perfil do parceiro |
| `session_service.py` | `SessionService` | Define estado de entrada do usuário (novo/em andamento/completo) |

## API pública por service

### `WhatsAppService`

```python
class WhatsAppService:
    def __init__(self) -> None: ...
    def enviar_resposta(self, to_number: str, resposta_bot: dict) -> None: ...
```

**Como é usado:**

- Chamado pelo `DispatchService` para disparar template a parceiros.
- O `main.py` envia mensagens diretamente via `InfobipClient` (não usa `WhatsAppService`) — duplicação histórica vinda do código pré-migração.

**Pontos não óbvios:**

- **Threading**: cada chamada de `enviar_resposta` dispara `threading.Thread` para não bloquear o caller. **Sem fila persistente** — se a app cai, mensagens em voo são perdidas.
- **Strip de prefixo**: aceita `to_number` com ou sem `whatsapp:` prefix — strip interno via `_strip_whatsapp_prefix`.
- **Padrão da mensagem (`resposta_bot`)**: dict com `tipo` (`texto`, `template`, `media`, `sequencia`, `combo_inicial`). Esse padrão é o contrato entre módulos do bot e este service — ver [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md#padr%C3%A3o-de-mensagem).
- **Retrocompatibilidade**: `_dict_to_positional_list` converte variáveis no estilo Twilio antigo (`{'1': 'a', '2': 'b'}`) para placeholders posicionais (`['a', 'b']`). Mantém callers não migrados funcionando. ⚠ Idealmente todos callers já passam `placeholders` direto.
- **Linguagem do template**: constante `DEFAULT_TEMPLATE_LANGUAGE = "pt_BR"`. Pra templates em outros idiomas, caller passa `language` no dict.

### `DispatchService`

```python
class DispatchService:
    def __init__(self) -> None: ...
    def enviar_oferta_para_prestadores(
        self,
        lista_uuids: list[str],
        pedido_uuid: str,
    ) -> dict: ...
```

**Como é usado:**

- Chamado pelo endpoint `POST /api/dispatch` quando um pedido novo entra no backoffice.
- Lê dados do pedido em `PEDIDOS_SERVICO`, busca cada parceiro em `PARCEIROS_PERFIL`, registra disparo em `PEDIDOS_DISPAROS`, e envia template via `WhatsAppService`.

**Pontos não óbvios:**

- **Template `oferta_servico`** com 9 placeholders posicionais: `[nome, atividade, numero, rua, bairro, data, observacao, valor, urgencia]`. ⚠ Re-cadastrar no portal Infobip com essa ordem antes de qualquer deploy.
- Retorna `{"status": "success", "enviados": <n>}` **mesmo se algum envio falhar** — falha individual vira log via `WhatsAppService`. Endpoint nunca propaga 5xx por falha de mensagem.
- **Sem retry**: se o INSERT em `PEDIDOS_DISPAROS` falha, o envio é pulado pra esse parceiro (sem aviso ao caller).

### `AzureBlobService`

```python
class AzureBlobService:
    def __init__(self) -> None: ...
    def upload_from_url(self, media_url: str, container_name: str, blob_name: str) -> str | None: ...
```

**Como é usado:**

- Chamado por `EtapaDocumentos` quando o parceiro envia foto (CNH, RG, selfie) via WhatsApp.
- Baixa do Infobip (URL privada com auth) e sobe pro Azure Blob (URL pública via container privado + SAS).

**Pontos não óbvios:**

- **Auth header**: `Authorization: App <INFOBIP-API-KEY>` para baixar mídia do Infobip. Diferente do Twilio antigo que usava Basic Auth.
- **⚠ URL pública vs privada**: dependendo da config do tenant Infobip, mídia inbound pode vir como URL pública (sem auth). Se receber 401/403 ao baixar, remover o header. Ver `MIGRATION_NOTES.md` item 5.
- **Container**: criado on-demand (`create_container` se não existe). Recomendável criar previamente com policy de acesso correta.
- **Retry transient no download**: `_download_midia` é decorado com `@transient_retry` — 2 tentativas em timeout/connection/5xx. 4xx (URL inválida, auth) loga WARNING e retorna `None` (não tenta de novo). Erro persistente retorna `None`.

### `ParceiroService`

```python
class ParceiroService:
    def __init__(self) -> None: ...
    # Dados pessoais
    def salvar_cnpj_inicial(self, whatsapp_id: str, cnpj: str) -> bool: ...
    def validar_cnpj_api(self, cnpj: str) -> tuple[bool, str]: ...
    def salvar_cpf(self, whatsapp_id: str, cpf: str) -> bool: ...
    def salvar_nome(self, whatsapp_id: str, nome: str) -> bool: ...
    # Endereço
    def buscar_cidade_por_cep(self, cep: str) -> tuple[str, str]: ...
    def salvar_cep_cidade(self, whatsapp_id: str, cep: str, cidade: str) -> bool: ...
    def salvar_rua(self, whatsapp_id: str, rua: str) -> bool: ...
    def salvar_bairro(self, whatsapp_id: str, bairro: str) -> bool: ...
    def finalizar_endereco_com_geo(self, whatsapp_id: str, numero: str) -> bool: ...
```

**Como é usado:**

- Chamado pelos módulos de etapa (`EtapaPessoal`, `EtapaEndereco`) durante o fluxo de onboarding.

**Pontos não óbvios:**

- **CNPJ é a chave de criação**: `salvar_cnpj_inicial` faz `MERGE` em `PARCEIROS_PERFIL` — cria o registro se não existe, atualiza se já existe. Gera `ParceiroUUID` aqui.
- **`validar_cnpj_api` é mock** — `time.sleep(1)` + regra fake "termina em `0000` é inválido". ⚠ Substituir por chamada Serpro/Receita Federal antes de prod.
- **`buscar_cidade_por_cep` também é mock** — retorna `("Belém", "PA")` fixo. ⚠ Substituir por ViaCEP em prod.
- **Geo**: `finalizar_endereco_com_geo` injeta `geography::Point(lat, long, 4326)` no SQL Server. Lat/long também mockados (random em torno de Belém). Substituir por Google Maps API em prod.

### `SessionService`

```python
class SessionService:
    def __init__(self) -> None: ...
    def verificar_entrada_usuario(self, whatsapp_id: str) -> dict: ...
    def iniciar_nova_sessao(self, whatsapp_id: str) -> None: ...
    def arquivar_usuario_antigo(self, whatsapp_id: str) -> None: ...
```

**Como é usado:**

- Chamado por `ModuloOnboarding.processar_inicio` no primeiro turno do chat.
- `verificar_entrada_usuario` retorna `{'tipo': 'NOVO_USUARIO' | 'CADASTRO_ANDAMENTO' | 'CADASTRO_COMPLETO'}` baseado em sessão ativa + status do perfil.

**Pontos não óbvios:**

- **Regra de ouro**: se existe perfil com status diferente de `ATIVO`/`EM_ANALISE`, sempre trata como "em andamento" mesmo que a sessão esteja `FINALIZADO`. Permite retomada após user abandonar o chat.
- **Arquivamento**: `arquivar_usuario_antigo` muda o `WhatsAppID` do registro antigo pra `<id>_v<hash>`, liberando o número original pra novo cadastro. Não deleta — preserva histórico LGPD.

## Pontos de fragilidade compartilhados

Itens que afetam mais de um service e valeria endereçar:

- **Retry transient implementado** em chamadas HTTP externas (Infobip, Blob download, ViaCEP, Google Maps) via `app/core/retry.py`. Dead-letter queue continua pendente (sem Service Bus) — falhas persistentes perdem a mensagem.
- **Mocks (Serpro, ViaCEP, Google Maps)** ainda no `ParceiroService`. ⚠ Bloqueador de prod.
- **`time.sleep`** em vários lugares (`WhatsAppService._processar_sequencia`, `main.enviar_sequencia_background`) — segura a thread. Pra escala, considerar Service Bus + worker.

## O que NÃO está aqui

- **Lógica de chat / FSM** → `app/bot_engine.py`
- **Etapas individuais do onboarding** → `app/modules/etapa_*`
- **Schemas Pydantic** → `app/schemas/`
- **Cliente HTTP do Infobip** → `app/integrations/infobip.py`
