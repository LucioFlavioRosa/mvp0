from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
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

    @staticmethod
    def geocodificar_texto(texto: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Geocodifica uma string livre (endereço, CEP, bairro ou cidade).
        Usado pelo BackofficeService no verificador de cobertura.
        Acrescenta 'Brasil' ao query para melhorar a precisão.
        """
        try:
            geolocator = Nominatim(user_agent="aegea_demand_management")
            location = geolocator.geocode(f"{texto}, Brasil", timeout=10)
            if location:
                return location.latitude, location.longitude
            return None, None
        except (GeocoderTimedOut, GeocoderServiceError) as e:
            print(f"🔥 Erro de geocodificação (texto livre) '{texto}': {e}")
            return None, None
        except Exception as e:
            print(f"🔥 Erro inesperado na geocodificação '{texto}': {e}")
            return None, None
