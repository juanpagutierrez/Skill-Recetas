"""
Repositorios para acceso a datos - Aplica Dependency Inversion Principle (DIP)
Define interfaces abstractas que permiten cambiar la implementación sin afectar el código cliente.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class IPersistenceAdapter(ABC):
    """Interface para adaptadores de persistencia (S3, FakeS3, etc.)"""
    
    @abstractmethod
    def get_attributes(self, request_envelope) -> Dict[str, Any]:
        """Obtiene atributos del usuario desde la fuente de persistencia"""
        pass
    
    @abstractmethod
    def save_attributes(self, request_envelope, attributes: Dict[str, Any]) -> None:
        """Guarda atributos del usuario en la fuente de persistencia"""
        pass
    
    @abstractmethod
    def delete_attributes(self, request_envelope) -> None:
        """Elimina atributos del usuario de la fuente de persistencia"""
        pass


class ICacheStrategy(ABC):
    """Interface para estrategias de cache"""
    
    @abstractmethod
    def get(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Obtiene datos del cache"""
        pass
    
    @abstractmethod
    def put(self, user_id: str, data: Dict[str, Any]) -> None:
        """Guarda datos en el cache"""
        pass
    
    @abstractmethod
    def invalidate(self, user_id: str) -> None:
        """Invalida el cache para un usuario"""
        pass


class IUserRepository(ABC):
    """Interface para repositorio de usuarios - abstrae el acceso a datos"""
    
    @abstractmethod
    def get_user_data(self, handler_input) -> Dict[str, Any]:
        """Obtiene los datos del usuario"""
        pass
    
    @abstractmethod
    def save_user_data(self, handler_input, data: Dict[str, Any]) -> None:
        """Guarda los datos del usuario"""
        pass
    
    @abstractmethod
    def get_initial_data(self) -> Dict[str, Any]:
        """Retorna la estructura inicial de datos de un usuario"""
        pass
