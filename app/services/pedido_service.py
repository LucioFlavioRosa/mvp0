from sqlalchemy.orm import Session, contains_eager
from sqlalchemy import distinct, select, case
from app.models import PedidoServico, Unidade, CatalogoServico
from typing import Optional, Dict, Any, List

class PedidoService:
    @staticmethod
    def get_pedidos(
        db: Session,
        status: Optional[str] = None,
        urgencia: Optional[str] = None,
        unidade_nome: Optional[str] = None,
        tipo_servico_nome: Optional[str] = None,
        bloco: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Retorna a lista de pedidos filtrados e ordena, imitando a lógica central do portal.
        Também retorna os valores únicos para os dropdowns de filtro.
        """
        # 1. Busca filtros disponíveis
        lista_status = db.execute(select(distinct(PedidoServico.StatusPedido)).where(PedidoServico.StatusPedido != None)).scalars().all()
        lista_urgencia = db.execute(select(distinct(PedidoServico.Urgencia)).where(PedidoServico.Urgencia != None)).scalars().all()
        
        stmt_unidades = select(distinct(Unidade.NomeUnidade)).join(PedidoServico, PedidoServico.UnidadeID == Unidade.UnidadeID)
        lista_unidades = db.execute(stmt_unidades).scalars().all() 

        stmt_tipos_servicos = select(distinct(CatalogoServico.Nome)).join(PedidoServico, PedidoServico.TipoServicoID == CatalogoServico.ServicoID)
        lista_tipos_servicos = db.execute(stmt_tipos_servicos).scalars().all() 

        stmt_blocos = select(distinct(PedidoServico.Bloco)).where(PedidoServico.Bloco != None)
        lista_blocos = db.execute(stmt_blocos).scalars().all()

        # 2. Query Principal de Pedidos
        stmt = (
            select(PedidoServico)
            .where(~PedidoServico.agrupamentos_vinculados.any())
            .join(PedidoServico.tipo_servico_ref) 
            .join(PedidoServico.unidade_obj) 
            .options(contains_eager(PedidoServico.tipo_servico_ref))
            .options(contains_eager(PedidoServico.unidade_obj))
        )            
        
        if status:
            stmt = stmt.where(PedidoServico.StatusPedido == status)
        if urgencia:
            stmt = stmt.where(PedidoServico.Urgencia == urgencia)
        if unidade_nome:
            stmt = stmt.where(Unidade.NomeUnidade == unidade_nome)
        if tipo_servico_nome:
            stmt = stmt.where(CatalogoServico.Nome == tipo_servico_nome)
        if bloco:
            stmt = stmt.where(PedidoServico.Bloco == bloco)
        
        # Ordenação Centralizada
        stmt = stmt.order_by(
            case(
                (PedidoServico.StatusPedido == 'AGUARDANDO', 1),
                (PedidoServico.StatusPedido == 'DISPARADO', 2),
                (PedidoServico.StatusPedido == 'VINCULADO', 3),
                (PedidoServico.StatusPedido == 'FINALIZADO', 4),
                (PedidoServico.StatusPedido == 'CANCELADO', 5),
                else_=6
            ),
            case(
                (PedidoServico.Urgencia == 'MAXIMA', 1),
                (PedidoServico.Urgencia == 'URGENTE', 2),
                (PedidoServico.Urgencia.in_(['JUIZADO', 'PROCON', 'IMPRENSA']), 3),
                (PedidoServico.Urgencia.in_(['DIRETORIA', 'OUVIDORIA', 'SOCIAL']), 4),
                (PedidoServico.Urgencia == 'NORMAL', 5),
                else_=6
            ),
            PedidoServico.PrazoConclusaoOS.asc()
        )
        
        pedidos_obj = db.execute(stmt).scalars().all()
        
        # Formatando para o Response Schema
        pedidos_formatados = []
        for p in pedidos_obj:
            p_dict = p.to_dict()
            p_dict['TempoMedio'] = p.tipo_servico_ref.TempoMedioExecucao if p.tipo_servico_ref else 0.0
            p_dict['Atividade'] = p.tipo_servico_ref.Nome if p.tipo_servico_ref else "Serviço Não Encontrado"
            p_dict['UnidadeNome'] = p.unidade_obj.NomeUnidade if p.unidade_obj else None
            p_dict['PrazoConclusaoOS'] = p.PrazoConclusaoOS.strftime('%d/%m/%Y %H:%M') if p.PrazoConclusaoOS else ""
            pedidos_formatados.append(p_dict)
            
        return {
            "pedidos": pedidos_formatados,
            "total": len(pedidos_formatados),
            "filtros_disponiveis": {
                "status": lista_status,
                "urgencias": lista_urgencia,
                "unidades": lista_unidades,
                "tipos_servico": lista_tipos_servicos,
                "blocos": lista_blocos
            }
        }
