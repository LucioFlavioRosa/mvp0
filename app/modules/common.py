class GeradorResposta:
    """
    Helper para padronizar as respostas.
    """

    @staticmethod
    def texto(msg, proximo_passo):
        """Mensagem de texto simples."""
        return proximo_passo, {
            'tipo': 'texto',
            'conteudo': msg
        }

    @staticmethod
    def media(legenda, url_arquivo, proximo_passo):
        """
        Envia um ARQUIVO (Vídeo, Imagem, PDF).
        O usuário verá o arquivo para baixar/assistir direto no chat.
        
        url_arquivo: Deve ser um link público (ex: Azure Blob ou Ngrok/static)
        """
        return proximo_passo, {
            'tipo': 'media',          # Indica ao main.py para usar a tag <Media>
            'legenda': legenda,       # Texto que vai junto com o arquivo
            'url': url_arquivo        # Onde o Twilio vai buscar o arquivo para entregar
        }

    @staticmethod
    def template(sid, variaveis, proximo_passo):
        """Dispara Template da Meta."""
        return proximo_passo, {
            'tipo': 'template',
            'sid': sid,
            'variaveis': variaveis
        }