from geopy.geocoders import Nominatim
from typing import Tuple, Optional

class GeocodingService:
    @staticmethod
    def geocodificar_endereco(rua: str, numero: str, bairro: str, cidade: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Gera as coordenadas geográficas (Lat, Lng) a partir de um endereço formatado.
        Utiliza o serviço gratuito Nominatim do OpenStreetMap.
        """
        try:
            geolocator = Nominatim(user_agent="aegea_demand_management")
            numero_str = numero if numero and numero != "S/N" else ""
            
            # Formata o endereço de forma otimizada para a API
            endereco_partes = [parte for parte in [rua, numero_str, bairro, cidade] if parte]
            endereco_completo = ", ".join(endereco_partes)
            
            location = geolocator.geocode(endereco_completo, timeout=5)
            
            if location:
                return location.latitude, location.longitude
            return None, None
            
        except Exception as e:
            print(f"🔥 Erro na geocodificação do endereço '{endereco_completo}': {e}")
            return None, None
