import uuid
import copy
from datetime import datetime, timedelta
from ask_sdk_core.handler_input import HandlerInput
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

# ==============================
# Prototype Pattern - Interfaz base
# ==============================
class Prototype(ABC):
    """Interfaz para el patrón Prototype"""
    
    @abstractmethod
    def clone(self) -> 'Prototype':
        """Crear una copia del objeto"""
        pass
    
    def deep_clone(self) -> 'Prototype':
        """Crear una copia profunda del objeto"""
        return copy.deepcopy(self)

def generar_id_unico():
    return str(uuid.uuid4())[:8]

def generar_id_preparacion():
    return str(uuid.uuid4())[:8]

class Preparacion(Prototype):
    """Modelo de Preparación con soporte para Prototype pattern"""
    
    def __init__(self, receta_id, nombre, nombre_persona, dias_preparacion=7):
        self.id = generar_id_preparacion()
        self.receta_id = receta_id
        self.nombre = nombre
        self.persona = nombre_persona if nombre_persona else "un amigo"
        self.fecha_preparacion = datetime.now().isoformat()
        self.fecha_limite = (datetime.now() + timedelta(days=dias_preparacion)).isoformat()
        self.estado = "activo"
    
    def clone(self) -> 'Preparacion':
        """Crear una copia de la preparación con nuevo ID y fechas"""
        nueva_prep = copy.copy(self)
        nueva_prep.id = generar_id_preparacion()
        nueva_prep.fecha_preparacion = datetime.now().isoformat()
        # Mantener la misma duración pero con fechas actuales
        fecha_original = datetime.fromisoformat(self.fecha_preparacion)
        fecha_limite_original = datetime.fromisoformat(self.fecha_limite)
        dias_diferencia = (fecha_limite_original - fecha_original).days
        nueva_prep.fecha_limite = (datetime.now() + timedelta(days=dias_diferencia)).isoformat()
        return nueva_prep
        
    def to_dict(self):
        return self.__dict__

    @property
    def fecha_limite_readable(self):
        try:
            return datetime.fromisoformat(self.fecha_limite).strftime("%d de %B")
        except:
            return "una semana"


# ==============================
# Builder Pattern para Preparacion
# ==============================
class PreparacionBuilder:
    """Builder para construir objetos Preparacion de forma fluida"""
    
    def __init__(self):
        self._receta_id = None
        self._nombre = None
        self._nombre_persona = None
        self._dias_preparacion = 7
    
    def for_receta(self, receta_id: str, nombre: str) -> 'PreparacionBuilder':
        """Establece la receta a preparar"""
        self._receta_id = receta_id
        self._nombre = nombre
        return self
    
    def by_person(self, nombre_persona: str) -> 'PreparacionBuilder':
        """Establece quién preparará la receta"""
        self._nombre_persona = nombre_persona
        return self
    
    def with_duration(self, dias: int) -> 'PreparacionBuilder':
        """Establece la duración de la preparación"""
        self._dias_preparacion = dias
        return self
    
    def build(self) -> Preparacion:
        """Construye y retorna la preparación final"""
        if not self._receta_id or not self._nombre:
            raise ValueError("Receta ID y nombre son requeridos")
        return Preparacion(self._receta_id, self._nombre, self._nombre_persona, self._dias_preparacion)
    
    def reset(self) -> 'PreparacionBuilder':
        """Resetea el builder"""
        self._receta_id = None
        self._nombre = None
        self._nombre_persona = None
        self._dias_preparacion = 7
        return self

class Receta(Prototype):
    """Modelo de Receta con soporte para Builder y Prototype patterns"""
    
    def __init__(self, nombre=None, ingredientes=None, tipo=None):
        self.nombre = self._normalize_value(nombre, "")
        self.ingredientes = self._normalize_value(ingredientes, "Desconocido")
        self.tipo = self._normalize_value(tipo, "Sin categoría")
        
        self.id = generar_id_unico()
        self.fecha_agregado = datetime.now().isoformat()
        self.total_preparaciones = 0
        self.estado = "disponible"

    @staticmethod
    def _normalize_value(value, default):
        if value and value.lower() in ["no sé", "no se", "no lo sé"]:
            return default
        return value if value else default
        
    def clone(self) -> 'Receta':
        """Crear una copia de la receta con nuevo ID"""
        nueva_receta = copy.copy(self)
        nueva_receta.id = generar_id_unico()  # Nuevo ID para la copia
        nueva_receta.fecha_agregado = datetime.now().isoformat()
        nueva_receta.total_preparaciones = 0
        nueva_receta.estado = "disponible"
        return nueva_receta
        
    def clone_as_variant(self, sufijo: str) -> 'Receta':
        """Crear una variante de la receta con nombre modificado"""
        variante = self.clone()
        variante.nombre = f"{self.nombre} {sufijo}"
        return variante

    def to_dict(self):
        return self.__dict__


# ==============================
# Builder Pattern para Receta
# ==============================
class RecetaBuilder:
    """Builder para construir objetos Receta de forma fluida"""
    
    def __init__(self):
        self._receta = Receta()
    
    def with_nombre(self, nombre: str) -> 'RecetaBuilder':
        """Establece el nombre de la receta"""
        self._receta.nombre = self._receta._normalize_value(nombre, "")
        return self
    
    def with_ingredientes(self, ingredientes: str) -> 'RecetaBuilder':
        """Establece los ingredientes de la receta"""
        self._receta.ingredientes = self._receta._normalize_value(ingredientes, "Desconocido")
        return self
    
    def with_tipo(self, tipo: str) -> 'RecetaBuilder':
        """Establece el tipo de la receta"""
        self._receta.tipo = self._receta._normalize_value(tipo, "Sin categoría")
        return self
    
    def with_estado(self, estado: str) -> 'RecetaBuilder':
        """Establece el estado de la receta"""
        self._receta.estado = estado
        return self
    
    def from_dict(self, data: Dict[str, Any]) -> 'RecetaBuilder':
        """Construye desde un diccionario"""
        if 'nombre' in data:
            self.with_nombre(data['nombre'])
        if 'ingredientes' in data:
            self.with_ingredientes(data['ingredientes'])
        if 'tipo' in data:
            self.with_tipo(data['tipo'])
        if 'estado' in data:
            self.with_estado(data['estado'])
        return self
    
    def from_prototype(self, receta_base: Receta) -> 'RecetaBuilder':
        """Construye basado en una receta existente (Prototype)"""
        self._receta = receta_base.clone()
        return self
    
    def build(self) -> Receta:
        """Construye y retorna la receta final"""
        return self._receta
    
    def reset(self) -> 'RecetaBuilder':
        """Resetea el builder para construir una nueva receta"""
        self._receta = Receta()
        return self