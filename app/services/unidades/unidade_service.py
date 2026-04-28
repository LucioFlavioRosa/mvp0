"""
UnidadeService — Domínio: Estrutural (Hierarquia Administrativa)

Responsável por:
  - Listagem consolidada: Empresas, Filiais, Unidades e Cidades
  - CRUD de Empresas
  - CRUD de Filiais
  - CRUD de Unidades
"""

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models import Unidade, PrecoServicoUnidade, CatalogoServico, Empresa, Filial, CatalogoCidadePara


class UnidadeService:

    # =========================================================================
    # LISTAGEM BÁSICA (já existente — preservada)
    # =========================================================================

    @staticmethod
    def listar_todas(db: Session) -> list:
        """
        Retorna todas as unidades cadastradas com id e nome.
        Utilizado para popular selects de formulários (ex: Nova OS).
        """
        unidades = db.execute(
            select(Unidade).order_by(Unidade.NomeUnidade)
        ).scalars().all()
        return [{"id": u.UnidadeID, "nome": u.NomeUnidade} for u in unidades]

    @staticmethod
    def listar_servicos_unidade(db: Session, unidade_id: int) -> list:
        """
        Retorna os serviços ativos vinculados a uma unidade específica,
        incluindo o preço tabelado para aquela unidade.
        """
        stmt = (
            select(PrecoServicoUnidade, CatalogoServico)
            .join(CatalogoServico, PrecoServicoUnidade.ServicoID == CatalogoServico.ServicoID)
            .where(PrecoServicoUnidade.UnidadeID == unidade_id)
            .where(PrecoServicoUnidade.Ativo == True)
            .order_by(CatalogoServico.Nome)
        )
        rows = db.execute(stmt).all()
        return [
            {
                "id": preco.ServicoID,
                "nome": servico.Nome,
                "preco": preco.Preco,
            }
            for preco, servico in rows
        ]

    # =========================================================================
    # LISTAGEM COMPLETA (ADMIN)
    # =========================================================================

    @staticmethod
    def listar_estrutural_completo(db: Session) -> dict:
        """
        Retorna o estado atual de toda a árvore administrativa:
        Empresas → Filiais → Unidades + lista de Cidades disponíveis.
        """
        empresas = db.execute(
            select(Empresa).order_by(Empresa.Nome)
        ).scalars().all()

        filiais = db.execute(
            select(Filial).order_by(Filial.Nome)
        ).scalars().all()

        unidades = db.execute(
            select(Unidade).order_by(Unidade.NomeUnidade)
        ).scalars().all()

        cidades = db.execute(
            select(CatalogoCidadePara).order_by(CatalogoCidadePara.NomeCidade)
        ).scalars().all()

        return {
            "empresas": [
                {"EmpresaID": e.EmpresaID, "Nome": e.Nome, "CNPJ": e.CNPJ}
                for e in empresas
            ],
            "filiais": [
                {
                    "FilialID": f.FilialID, "EmpresaID": f.EmpresaID,
                    "Nome": f.Nome, "CNPJ": f.CNPJ,
                    "Regiao": f.Regiao, "Estado": f.Estado
                }
                for f in filiais
            ],
            "unidades": [
                {
                    "UnidadeID": u.UnidadeID, "FilialID": u.FilialID,
                    "CidadeID": u.CidadeID, "NomeUnidade": u.NomeUnidade,
                    "CNPJ": u.CNPJ, "CodigoFilial": u.CodigoFilial,
                    "Bloco": u.Bloco, "FornecimentoMateriais": u.FornecimentoMateriais
                }
                for u in unidades
            ],
            "cidades": [
                {"CidadeID": c.CidadeID, "NomeCidade": c.NomeCidade, "SubregiaoID": c.SubregiaoID}
                for c in cidades
            ]
        }

    # =========================================================================
    # CRUD EMPRESA
    # =========================================================================

    @staticmethod
    def criar_empresa(db: Session, dados: dict) -> Empresa:
        """Cria uma nova Empresa."""
        empresa = Empresa()
        empresa.Nome = dados["nome"]
        empresa.CNPJ = dados.get("cnpj")
        db.add(empresa)
        db.commit()
        db.refresh(empresa)
        return empresa

    @staticmethod
    def editar_empresa(db: Session, empresa_id: int, dados: dict) -> Empresa:
        """Edita uma Empresa existente. Suporta atualização parcial."""
        empresa = db.get(Empresa, empresa_id)
        if not empresa:
            raise ValueError(f"Empresa ID {empresa_id} não encontrada.")
        
        if "nome" in dados:
            empresa.Nome = dados["nome"]
        if "cnpj" in dados:
            empresa.CNPJ = dados["cnpj"]

        db.commit()
        db.refresh(empresa)
        return empresa

    @staticmethod
    def deletar_empresa(db: Session, empresa_id: int) -> None:
        """Remove uma Empresa. Lança ValueError se não encontrada."""
        empresa = db.get(Empresa, empresa_id)
        if not empresa:
            raise ValueError(f"Empresa ID {empresa_id} não encontrada.")
        db.delete(empresa)
        db.commit()

    # =========================================================================
    # CRUD FILIAL
    # =========================================================================

    @staticmethod
    def criar_filial(db: Session, dados: dict) -> Filial:
        """Cria uma nova Filial. Valida se a Empresa-pai existe."""
        empresa = db.get(Empresa, dados["empresa_id"])
        if not empresa:
            raise ValueError(f"Empresa ID {dados['empresa_id']} não encontrada.")
        filial = Filial()
        filial.EmpresaID = dados["empresa_id"]
        filial.Nome = dados["nome"]
        filial.CNPJ = dados.get("cnpj")
        filial.Regiao = dados.get("regiao")
        filial.Estado = dados.get("estado")
        db.add(filial)
        db.commit()
        db.refresh(filial)
        return filial

    @staticmethod
    def editar_filial(db: Session, filial_id: int, dados: dict) -> Filial:
        """Edita uma Filial existente. Suporta atualização parcial."""
        filial = db.get(Filial, filial_id)
        if not filial:
            raise ValueError(f"Filial ID {filial_id} não encontrada.")
        
        if "empresa_id" in dados:
            empresa = db.get(Empresa, dados["empresa_id"])
            if not empresa:
                raise ValueError(f"Empresa ID {dados['empresa_id']} não encontrada.")
            filial.EmpresaID = dados["empresa_id"]
        
        if "nome" in dados:
            filial.Nome = dados["nome"]
        if "cnpj" in dados:
            filial.CNPJ = dados["cnpj"]
        if "regiao" in dados:
            filial.Regiao = dados["regiao"]
        if "estado" in dados:
            filial.Estado = dados["estado"]

        db.commit()
        db.refresh(filial)
        return filial

    @staticmethod
    def deletar_filial(db: Session, filial_id: int) -> None:
        """Remove uma Filial. Lança ValueError se não encontrada."""
        filial = db.get(Filial, filial_id)
        if not filial:
            raise ValueError(f"Filial ID {filial_id} não encontrada.")
        db.delete(filial)
        db.commit()

    # =========================================================================
    # CRUD UNIDADE
    # =========================================================================

    @staticmethod
    def criar_unidade(db: Session, dados: dict) -> Unidade:
        """Cria uma nova Unidade. Valida se o CidadeID existe (FK obrigatória)."""
        cidade = db.get(CatalogoCidadePara, dados["cidade_id"])
        if not cidade:
            raise ValueError(f"Cidade ID {dados['cidade_id']} inválida ou não encontrada.")
        unidade = Unidade()
        unidade.CidadeID = dados["cidade_id"]
        unidade.NomeUnidade = dados["nome_unidade"]
        unidade.FilialID = dados.get("filial_id")
        unidade.CNPJ = dados.get("cnpj")
        unidade.CodigoFilial = dados.get("codigo_filial")
        unidade.Bloco = dados.get("bloco")
        unidade.FornecimentoMateriais = dados.get("materiais")
        db.add(unidade)
        db.commit()
        db.refresh(unidade)
        return unidade

    @staticmethod
    def editar_unidade(db: Session, unidade_id: int, dados: dict) -> Unidade:
        """Edita uma Unidade existente. Suporta atualização parcial."""
        unidade = db.get(Unidade, unidade_id)
        if not unidade:
            raise ValueError(f"Unidade ID {unidade_id} não encontrada.")
        
        if "cidade_id" in dados:
            cidade = db.get(CatalogoCidadePara, dados["cidade_id"])
            if not cidade:
                raise ValueError(f"Cidade ID {dados['cidade_id']} inválida ou não encontrada.")
            unidade.CidadeID = dados["cidade_id"]

        if "nome_unidade" in dados:
            unidade.NomeUnidade = dados["nome_unidade"]
        if "filial_id" in dados:
            unidade.FilialID = dados["filial_id"]
        if "cnpj" in dados:
            unidade.CNPJ = dados["cnpj"]
        if "codigo_filial" in dados:
            unidade.CodigoFilial = dados["codigo_filial"]
        if "bloco" in dados:
            unidade.Bloco = dados["bloco"]
        if "materiais" in dados:
            unidade.FornecimentoMateriais = dados["materiais"]

        db.commit()
        db.refresh(unidade)
        return unidade

    @staticmethod
    def deletar_unidade(db: Session, unidade_id: int) -> None:
        """Remove uma Unidade. Lança ValueError se não encontrada."""
        unidade = db.get(Unidade, unidade_id)
        if not unidade:
            raise ValueError(f"Unidade ID {unidade_id} não encontrada.")
        db.delete(unidade)
        db.commit()
