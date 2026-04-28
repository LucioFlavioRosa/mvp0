"""
ServicoService — Domínio: Catálogo de Serviços & Materiais

Responsável por:
  - Listagem completa do catálogo de serviços com todos os atributos
  - Listagem de unidades com seus serviços configurados e preços
  - CRUD do catálogo (criar, editar)
  - Upsert de configuração de preço por unidade
  - Listagem de materiais
"""

from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select
from app.models import CatalogoServico, PrecoServicoUnidade, Material, Unidade


class ServicoService:

    # =========================================================================
    # CATÁLOGO GERAL
    # =========================================================================

    @staticmethod
    def listar_geral(db: Session) -> list:
        """
        Retorna o catálogo completo de serviços com todos os atributos.
        Utilizado tanto pela listagem administrativa quanto pelo formulário
        de Nova OS (para popular o select de serviços).
        """
        servicos = db.execute(
            select(CatalogoServico).order_by(CatalogoServico.Nome)
        ).scalars().all()

        return [
            {
                "ServicoID": s.ServicoID,
                "CodigoServico": s.CodigoServico,
                "Nome": s.Nome,
                "Descricao": s.Descricao,
                "TipoVeiculo": s.TipoVeiculo,
                "EPI": s.EPI,
                "Perfil": s.Perfil,
                "FormularioResposta": s.FormularioResposta,
                "TempoMedioExecucao": s.TempoMedioExecucao,
                "TempoMaximo": s.TempoMaximo,
            }
            for s in servicos
        ]

    @staticmethod
    def criar_servico(db: Session, dados: dict) -> CatalogoServico:
        """Cria um novo serviço no catálogo."""
        servico = CatalogoServico()
        servico.CodigoServico = dados["codigo_servico"]
        servico.Nome = dados["nome"]
        servico.Descricao = dados["descricao"]
        servico.TipoVeiculo = dados.get("tipo_veiculo")
        servico.EPI = dados.get("epi")
        servico.Perfil = dados.get("perfil")
        servico.FormularioResposta = dados.get("formulario_resposta")
        servico.TempoMedioExecucao = dados.get("tempo_medio_execucao")
        servico.TempoMaximo = dados.get("tempo_maximo")
        db.add(servico)
        db.commit()
        db.refresh(servico)
        return servico

    @staticmethod
    def editar_servico(db: Session, servico_id: int, dados: dict) -> CatalogoServico:
        """Edita um serviço existente. Suporta atualização parcial."""
        servico = db.get(CatalogoServico, servico_id)
        if not servico:
            raise ValueError(f"Serviço ID {servico_id} não encontrado.")

        if "codigo_servico" in dados:
            servico.CodigoServico = dados["codigo_servico"]
        if "nome" in dados:
            servico.Nome = dados["nome"]
        if "descricao" in dados:
            servico.Descricao = dados["descricao"]
        if "tipo_veiculo" in dados:
            servico.TipoVeiculo = dados["tipo_veiculo"]
        if "epi" in dados:
            servico.EPI = dados["epi"]
        if "perfil" in dados:
            servico.Perfil = dados["perfil"]
        if "formulario_resposta" in dados:
            servico.FormularioResposta = dados["formulario_resposta"]
        if "tempo_medio_execucao" in dados:
            servico.TempoMedioExecucao = dados["tempo_medio_execucao"]
        if "tempo_maximo" in dados:
            servico.TempoMaximo = dados["tempo_maximo"]

        db.commit()
        db.refresh(servico)
        return servico

    # =========================================================================
    # CONFIGURAÇÃO POR UNIDADE
    # =========================================================================

    @staticmethod
    def listar_servicos_completo_por_unidade(db: Session) -> list:
        """
        Retorna todas as unidades com seus serviços configurados e preços.
        Os campos TempoMedioExecucao e TempoMaximo são lidos do CatalogoServico
        (fonte de verdade), não da tabela de preços.
        """
        unidades = db.execute(
            select(Unidade)
            .options(
                selectinload(Unidade.servicos_configurados)
                .selectinload(PrecoServicoUnidade.servico_ref)
            )
            .order_by(Unidade.NomeUnidade)
        ).scalars().all()

        resultado = []
        for u in unidades:
            configs = []
            for config in u.servicos_configurados:
                s = config.servico_ref
                configs.append({
                    "ServicoID": config.ServicoID,
                    "Nome": s.Nome if s else f"ID {config.ServicoID}",
                    "Preco": config.Preco,
                    "TempoMedioExecucao": s.TempoMedioExecucao if s else None,
                    "TempoMaximo": s.TempoMaximo if s else None,
                    "FatorExtra": config.FatorExtra,
                    "Ativo": config.Ativo,
                })
            resultado.append({
                "UnidadeID": u.UnidadeID,
                "NomeUnidade": u.NomeUnidade,
                "servicos_configurados": configs,
            })

        return resultado

    @staticmethod
    def vincular_servico_unidade(db: Session, dados: dict) -> PrecoServicoUnidade:
        """
        Upsert na tabela PRECOS_SERVICOS_UNIDADE.
        Cria o vínculo se não existir; atualiza se já existir.
        """
        unidade_id = dados["unidade_id"]
        servico_id = dados["servico_id"]

        # Tenta buscar registro existente (PK composta)
        config = db.get(PrecoServicoUnidade, (unidade_id, servico_id))

        if not config:
            config = PrecoServicoUnidade()
            config.UnidadeID = unidade_id
            config.ServicoID = servico_id
            db.add(config)

        config.Preco = dados.get("preco", 0.0)
        config.FatorExtra = dados.get("fator_extra", 1.0)
        config.Ativo = dados.get("ativo", True)

        db.commit()
        db.refresh(config)
        return config

    # =========================================================================
    # MATERIAIS
    # =========================================================================

    @staticmethod
    def listar_materiais(db: Session) -> list:
        """Retorna todos os materiais do catálogo."""
        materiais = db.execute(
            select(Material).order_by(Material.Descricao)
        ).scalars().all()
        return [
            {
                "MaterialID": m.MaterialID,
                "Descricao": m.Descricao,
                "TipoMaterial": m.TipoMaterial,
            }
            for m in materiais
        ]
