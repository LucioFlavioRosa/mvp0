from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import select, insert
from app.models import PedidoServico, ParceiroPerfil, PedidoDisparo
from app.services.infra.twilio_service import TwilioService

class DispatchService:
    def __init__(self):
        self.twilio = TwilioService()
        # SID do Template
        self.TEMPLATE_OFERTA = "HXe06780de5d2ec3b456c82275071f6bfc" 

    def enviar_oferta_para_prestadores(self, db: Session, lista_uuids, pedido_uuid):
        """
        Busca dados detalhados do pedido e notifica a lista de prestadores
        registrando o disparo na tabela PEDIDOS_DISPAROS via ORM.
        """
        # 1. Busca dados do Pedido via ORM
        pedido = db.query(PedidoServico).filter(PedidoServico.PedidoID == pedido_uuid).first()
        
        if not pedido:
            return {"status": "error", "message": f"Pedido {pedido_uuid} não encontrado"}

        # Tratamento de Dados (Preservando lógica legada)
        atividade = (pedido.tipo_servico_ref.Nome if pedido.tipo_servico_ref else None) or pedido.Atividade or "Serviço Geral"
        rua = pedido.Rua or "Rua não informada"
        numero = pedido.Numero or "S/N"
        bairro = pedido.Bairro or "Bairro não informado"
        observacao = pedido.Observacao or "Verificar detalhes no app"
        valor = pedido.Valor or 0.0
        urgencia = pedido.Urgencia or "Normal"

        valor_fmt = f"{valor:.2f}".replace('.', ',')
        data_fmt = pedido.DataLimite.strftime('%d/%m/%Y') if isinstance(pedido.DataLimite, datetime) else str(pedido.DataLimite or "A combinar")

        count_envios = 0

        # 2. Loop pelos Parceiros
        for p_uuid in lista_uuids:
            parceiro = db.query(ParceiroPerfil).filter(ParceiroPerfil.ParceiroUUID == p_uuid).first()
            
            if parceiro:
                whatsapp_id = parceiro.WhatsAppID
                nome_parceiro = parceiro.NomeCompleto
                primeiro_nome = nome_parceiro.split()[0] if nome_parceiro else "Parceiro"

                # 🟢 A) REGISTRA O DISPARO via ORM
                novo_disparo = PedidoDisparo(
                    PedidoID=pedido_uuid,
                    ParceiroUUID=p_uuid,
                    Status='ENVIADO',
                    DataAtualizacao=datetime.now()
                )
                db.add(novo_disparo)
                
                try:
                    db.commit()
                    # B) MONTA VARIÁVEIS PARA O TEMPLATE
                    variaveis_template = {
                        '1': primeiro_nome,  
                        '2': atividade,      
                        '3': str(numero),    
                        '4': rua,            
                        '5': bairro,         
                        '6': data_fmt,       
                        '7': observacao,     
                        '8': valor_fmt,      
                        '9': urgencia        
                    }

                    # C) ENVIA WHATSAPP
                    msg_template = {
                        'tipo': 'template',
                        'sid': self.TEMPLATE_OFERTA,
                        'variaveis': variaveis_template
                    }
                    
                    self.twilio.enviar_resposta(whatsapp_id, msg_template)
                    count_envios += 1
                except Exception as e:
                    db.rollback()
                    print(f"🔥 Erro ao registrar disparo para {p_uuid}: {e}")

        return {"status": "success", "enviados": count_envios}
