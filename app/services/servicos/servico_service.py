from sqlalchemy.orm import Session
from sqlalchemy import select
from app.models import CatalogoServico


class ServicoService:
    @staticmethod
    def listar_geral(db: Session) -> list:
        """
        Retorna o catálogo completo de serviços cadastrados.
        """
        servicos = db.execute(
            select(CatalogoServico).order_by(CatalogoServico.Nome)
        ).scalars().all()
        return [
            {
                "id": s.ServicoID,
                "codigo": s.CodigoServico,
                "nome": s.Nome,
                "descricao": s.Descricao,
            }
            for s in servicos
        ]
