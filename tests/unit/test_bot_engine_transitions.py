"""Testes para BotEngine: sessao, oferta intercept, transicoes criticas.

Estrategia: criar BotEngine via __new__ + injetar self.db / self.oferta /
self.onboarding diretamente. Evita o __init__ pesado (que instancia 7
modulos de etapa, alguns com Google Maps client no construtor).

Foco minimalista: testar o "router" (processar_mensagem) e os helpers de
sessao (_get_session, _save_session), nao as 50+ transicoes do FSM.

Skill: aplicada do catalogo "Tipo 8 - State machine".
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def bot(mock_settings):
    """BotEngine sem __init__ + atributos injetados.

    Cada teste pode customizar:
        bot.db.execute_read_one.return_value = ("AGUARDANDO_CPF", "{}", 10, dt)
        bot.oferta.verificar_oferta_pendente.return_value = None
        bot.onboarding.processar_inicio.return_value = ('NOVO_STEP', {...})
    """
    from app.bot_engine import BotEngine
    instance = BotEngine.__new__(BotEngine)
    instance.db = MagicMock(name="db")
    instance.db.execute_read_one.return_value = None
    instance.db.execute_write.return_value = True
    instance.db.execute_write_with_rowcount.return_value = 1  # 1 linha = sucesso default

    # Modulos de etapa - todos mocados
    instance.onboarding = MagicMock(name="onboarding")
    instance.pessoal = MagicMock(name="pessoal")
    instance.endereco = MagicMock(name="endereco")
    instance.habilidades = MagicMock(name="habilidades")
    instance.veiculos = MagicMock(name="veiculos")
    instance.disponibilidade = MagicMock(name="disponibilidade")
    instance.documentos = MagicMock(name="documentos")
    instance.oferta = MagicMock(name="oferta")
    instance.oferta.verificar_oferta_pendente.return_value = None  # default

    # Tabelas estaticas do BotEngine (vem do __init__ que pulamos)
    instance.SAUDACOES = ['OI', 'OLA', 'MENU', 'AJUDA', 'INICIO', 'RECOMECAR']
    instance.MAPA_RETOMADA = {
        'AGUARDANDO_CNPJ': "Digite seu CNPJ:",
        'AGUARDANDO_CPF': "Digite seu CPF:",
    }
    return instance


# ===========================================================================
# _get_session - sessao nova, ativa, expirada
# ===========================================================================
def test_get_session_retorna_START_quando_usuario_novo(bot):
    """SELECT vazio = sessao nao existe = NOVO_USUARIO. Inicio de fluxo.
    last_update vem None pra forcar INSERT no save (sem optimistic check)."""
    bot.db.execute_read_one.return_value = None

    step, dados, last_update = bot._get_session("5511999")

    assert step == "START"
    assert dados == {}
    assert last_update is None


def test_get_session_retorna_step_atual_quando_sessao_ativa(bot):
    """Sessao com LastUpdate < 5min retorna step, dados parseados e
    timestamp raw pra optimistic locking."""
    from datetime import datetime
    last_upd = datetime(2026, 5, 13, 10, 0, 0)
    bot.db.execute_read_one.return_value = (
        "AGUARDANDO_CPF",
        '{"cnpj": "12345678000100"}',
        10,  # 10s desde LastUpdate, dentro do timeout
        last_upd,
    )

    step, dados, last_update = bot._get_session("5511999")

    assert step == "AGUARDANDO_CPF"
    assert dados == {"cnpj": "12345678000100"}
    assert last_update == last_upd  # timestamp preservado pra save


def test_get_session_retorna_START_e_grava_step_backup_em_timeout(bot):
    """Sessao com inativo > 300s (5 min) e step relevante: forca START
    pra disparar 'retomada inteligente', preservando step_backup.
    last_update continua sendo retornado (sessao existe no DB)."""
    from datetime import datetime
    last_upd = datetime(2026, 5, 13, 9, 0, 0)
    bot.db.execute_read_one.return_value = (
        "AGUARDANDO_RUA",
        '{"cep": "01310-100"}',
        450,  # 7.5 min - expirou
        last_upd,
    )

    step, dados, last_update = bot._get_session("5511999")

    assert step == "START"
    assert dados["step_backup"] == "AGUARDANDO_RUA"
    assert dados["cep"] == "01310-100"  # dados preservados
    assert last_update == last_upd


def test_get_session_nao_grava_step_backup_para_passos_terminais(bot):
    """Steps 'START', 'FINALIZADO', etc nao geram step_backup mesmo
    apos timeout - nao tem o que retomar."""
    from datetime import datetime
    bot.db.execute_read_one.return_value = (
        "FINALIZADO",
        '{}',
        1000,
        datetime(2026, 5, 13, 8, 0, 0),
    )

    step, dados, _ = bot._get_session("5511999")

    assert step == "START"
    assert "step_backup" not in dados


# ===========================================================================
# _save_session - START / NO_UPDATE skipados, demais persistem
# ===========================================================================
def test_save_session_nao_grava_quando_step_eh_START(bot):
    """START e no-op intencional - retorna True sem tocar DB."""
    resultado = bot._save_session("5511999", "START", {"foo": "bar"})

    assert resultado is True
    bot.db.execute_write_with_rowcount.assert_not_called()


def test_save_session_nao_grava_quando_step_eh_NO_UPDATE(bot):
    """NO_UPDATE eh sinalizacao do bot pra nao mexer no estado da sessao."""
    resultado = bot._save_session("5511999", "NO_UPDATE", {})

    assert resultado is True
    bot.db.execute_write_with_rowcount.assert_not_called()


def test_save_session_grava_step_valido_com_dados_json(bot):
    """Sessao nova (last_update=None): MERGE faz INSERT, rowcount=1, sucesso."""
    resultado = bot._save_session("5511999", "AGUARDANDO_CPF", {"cnpj": "1234"})

    assert resultado is True
    bot.db.execute_write_with_rowcount.assert_called_once()
    # Confirma que dados foram serializados como JSON e last_update=None no SQL
    sql, params = bot.db.execute_write_with_rowcount.call_args.args
    # params = (clean_id, last_update, step, dados_str, clean_id, step, dados_str)
    assert params[0] == "5511999"
    assert params[1] is None  # last_update None pra session nova
    assert params[2] == "AGUARDANDO_CPF"
    assert '"cnpj": "1234"' in params[3]


# ===========================================================================
# _save_session - OPTIMISTIC LOCKING (race conditions)
# ===========================================================================
def test_save_session_passa_last_update_no_sql(bot):
    """Sessao existente (last_update fornecido) deve ir como segundo parametro
    no SQL, casando com a clausula WHEN MATCHED AND target.LastUpdate = ?."""
    from datetime import datetime
    last_upd = datetime(2026, 5, 13, 10, 0, 0)

    resultado = bot._save_session("5511999", "AGUARDANDO_CPF", {"cnpj": "12"}, last_upd)

    assert resultado is True
    sql, params = bot.db.execute_write_with_rowcount.call_args.args
    assert params[1] == last_upd  # last_update passado ao WHERE do MERGE


def test_save_session_detecta_conflito_quando_rowcount_zero(bot):
    """Race condition: outro worker atualizou a mesma sessao entre nosso
    _get_session e este _save_session. Backend retorna rowcount=0 (WHEN
    MATCHED falha porque target.LastUpdate ja mudou). Devemos detectar e
    retornar False (caller decide se aborta ou loga e ignora)."""
    from datetime import datetime
    bot.db.execute_write_with_rowcount.return_value = 0  # conflito!

    resultado = bot._save_session(
        "5511999",
        "AGUARDANDO_CPF",
        {"cnpj": "12"},
        datetime(2026, 5, 13, 10, 0, 0),
    )

    assert resultado is False  # conflito detectado, save nao aplicou


def test_save_session_tolera_rowcount_indefinido_como_sucesso(bot):
    """pyodbc as vezes retorna rowcount=-1 quando o driver nao reporta. Esse
    valor nao significa falha - so falta de info. Aceitamos como sucesso
    pessimista pra nao perder writes legitimos."""
    bot.db.execute_write_with_rowcount.return_value = -1

    resultado = bot._save_session("5511999", "AGUARDANDO_CPF", {}, None)

    assert resultado is True


def test_save_session_grava_quando_last_update_bate(bot):
    """Caminho feliz com optimistic lock: nenhum outro worker tocou a sessao,
    LastUpdate continua igual, MERGE aplica UPDATE, rowcount=1."""
    from datetime import datetime
    bot.db.execute_write_with_rowcount.return_value = 1

    resultado = bot._save_session(
        "5511999",
        "AGUARDANDO_CPF",
        {"cnpj": "12345678000100"},
        datetime(2026, 5, 13, 10, 0, 0),
    )

    assert resultado is True
    bot.db.execute_write_with_rowcount.assert_called_once()


# ===========================================================================
# processar_mensagem - oferta intercepta fluxo de cadastro
# ===========================================================================
def test_processar_mensagem_intercepta_quando_existe_oferta_pendente(bot):
    """Politica de prioridade: se ha oferta pendente, ela vence o cadastro.
    Bot nao roteia pra etapa - delega pra EtapaOferta."""
    bot.oferta.verificar_oferta_pendente.return_value = {
        "pedido_uuid": "ped-1",
        "atividade": "Encanador",
    }
    bot.oferta.processar_resposta.return_value = (
        "STEP_DUMMY",
        {"tipo": "texto", "conteudo": "Recebemos sua resposta"},
    )

    resposta = bot.processar_mensagem("5511999", "ACEITO")

    assert resposta == {"tipo": "texto", "conteudo": "Recebemos sua resposta"}
    bot.oferta.processar_resposta.assert_called_once()
    # NAO consultou sessao normal - oferta prevaleceu
    bot.db.execute_read_one.assert_not_called()


# ===========================================================================
# processar_mensagem - saudacao no meio do fluxo grava step_backup
# ===========================================================================
def test_processar_mensagem_saudacao_no_meio_do_fluxo_grava_step_backup(bot):
    """User digita 'OI' enquanto esta em AGUARDANDO_CPF.
    Bot deve gravar step_backup=AGUARDANDO_CPF e mostrar menu/inicio."""
    from datetime import datetime
    bot.oferta.verificar_oferta_pendente.return_value = None
    bot.db.execute_read_one.return_value = (
        "AGUARDANDO_CPF",
        '{}',
        5,
        datetime(2026, 5, 13, 10, 0, 0),
    )
    bot.onboarding.processar_inicio.return_value = (
        "DECISAO_CONTINUAR",
        {"tipo": "texto", "conteudo": "Ola, quer continuar?"},
    )

    resposta = bot.processar_mensagem("5511999", "OI")

    assert resposta["conteudo"] == "Ola, quer continuar?"
    # Confirma que step_backup foi gravado na sessao (via execute_write_with_rowcount agora)
    bot.db.execute_write_with_rowcount.assert_called_once()
    _, params = bot.db.execute_write_with_rowcount.call_args.args
    # params = (clean_id, last_update, step, dados_str, ...)
    assert '"step_backup": "AGUARDANDO_CPF"' in params[3]
