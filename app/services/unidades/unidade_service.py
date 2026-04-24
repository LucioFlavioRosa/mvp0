from sqlalchemy.orm import Session
from sqlalchemy import select
from app.models import Unidade, PrecoServicoUnidade, CatalogoServico


class UnidadeService:
    @staticmethod
    def listar_todas(db: Session) -> list:
        """
        Retorna todas as unidades cadastradas com id e nome.
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
