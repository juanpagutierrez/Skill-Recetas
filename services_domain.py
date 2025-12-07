"""
Servicios de dominio - Aplica Single Responsibility Principle (SRP)
Cada servicio tiene una única razón para cambiar y una responsabilidad bien definida.
"""
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import logging

from models import Receta, Preparacion, generar_id_unico
from repositories import IUserRepository
from config import RECETAS_POR_PAGINA

logger = logging.getLogger(__name__)


# ==============================
# Servicios de Búsqueda - Single Responsibility
# ==============================
class RecetaSearchService:
    """Servicio encargado únicamente de buscar recetas"""
    
    @staticmethod
    def buscar_por_nombre(recetas: List[Dict], nombre_busqueda: str) -> List[Dict]:
        """Busca recetas por nombre y devuelve una lista de coincidencias"""
        if not nombre_busqueda:
            return []
        
        nombre_lower = nombre_busqueda.lower().strip()
        resultados = []
        
        for receta in recetas:
            if not isinstance(receta, dict):
                continue
            receta_nombre_lower = receta.get("nombre", "").lower()
            
            # Coincidencia exacta primero
            if receta_nombre_lower == nombre_lower:
                resultados.insert(0, receta)
            # Coincidencia parcial después
            elif nombre_lower in receta_nombre_lower:
                resultados.append(receta)
        
        return resultados
    
    @staticmethod
    def buscar_por_nombre_exacto(recetas: List[Dict], nombre: str) -> Optional[Dict]:
        """Busca una receta por nombre exacto"""
        if not nombre:
            return None
        
        nombre_lower = nombre.lower().strip()
        for receta in recetas:
            if isinstance(receta, dict):
                if receta.get("nombre", "").lower() == nombre_lower:
                    return receta
        return None
    
    @staticmethod
    def buscar_por_tipo(recetas: List[Dict], tipo_busqueda: str) -> List[Dict]:
        """Busca recetas por tipo"""
        if not tipo_busqueda:
            return []
        
        tipo_lower = tipo_busqueda.lower().strip()
        resultados = []
        
        for receta in recetas:
            if isinstance(receta, dict):
                tipo_receta = receta.get("tipo", "").lower()
                if tipo_lower in tipo_receta or tipo_receta in tipo_lower:
                    resultados.append(receta)
        
        return resultados


# ==============================
# Servicio de Sincronización de Estados
# ==============================
class RecetaStateService:
    """Servicio encargado de sincronizar estados de recetas"""
    
    @staticmethod
    def sincronizar_estados(recetas: List[Dict], preparaciones: List[Dict]) -> List[Dict]:
        """Sincroniza los estados de las recetas basándose en las preparaciones activas"""
        # Asegurar que todas las recetas tienen ID
        for receta in recetas:
            if not receta.get("id"):
                receta["id"] = generar_id_unico()
        
        # Actualizar estados según preparaciones
        ids_preparando = {p.get("receta_id") for p in preparaciones if p.get("receta_id")}
        
        for receta in recetas:
            receta_id = receta.get("id")
            if receta_id in ids_preparando:
                receta["estado"] = "preparando"
            else:
                receta["estado"] = "disponible"
        
        return recetas


# ==============================
# Servicio de Gestión de Recetas - Single Responsibility
# ==============================
class RecetaService:
    """Servicio para operaciones CRUD de recetas"""
    
    def __init__(self, repository: IUserRepository, search_service: RecetaSearchService):
        self._repository = repository
        self._search = search_service
    
    def agregar_receta(self, handler_input, nombre: str, ingredientes: str, tipo: str) -> Optional[Receta]:
        """Agrega una nueva receta al recetario"""
        user_data = self._repository.get_user_data(handler_input)
        recetas = user_data.get("recetas_disponibles", [])
        
        # Verificar duplicados
        if any(receta.get("nombre", "").lower() == nombre.lower() for receta in recetas):
            return None  # Ya existe
        
        nueva_receta = Receta(nombre=nombre, ingredientes=ingredientes, tipo=tipo)
        recetas.append(nueva_receta.to_dict())
        
        # Actualizar estadísticas
        stats = user_data.setdefault("estadisticas", {})
        stats["total_recetas"] = len(recetas)
        
        self._repository.save_user_data(handler_input, user_data)
        return nueva_receta
    
    def obtener_recetas(self, handler_input) -> List[Dict]:
        """Obtiene todas las recetas del usuario"""
        user_data = self._repository.get_user_data(handler_input)
        return user_data.get("recetas_disponibles", [])
    
    def buscar_recetas(self, handler_input, nombre: str) -> List[Dict]:
        """Busca recetas por nombre"""
        recetas = self.obtener_recetas(handler_input)
        return self._search.buscar_por_nombre(recetas, nombre)
    
    def eliminar_receta(self, handler_input, nombre: str) -> Optional[Dict]:
        """Elimina una receta por nombre"""
        user_data = self._repository.get_user_data(handler_input)
        recetas = user_data.get("recetas_disponibles", [])
        preparaciones_activas = user_data.get("preparaciones_activas", [])
        
        receta_a_eliminar = self._search.buscar_por_nombre_exacto(recetas, nombre)
        
        if not receta_a_eliminar:
            return None  # No encontrada
        
        receta_id = receta_a_eliminar.get("id")
        
        # Verificar si está en preparación
        if any(p.get("receta_id") == receta_id for p in preparaciones_activas):
            return {"error": "esta_preparando"}
        
        try:
            recetas_actualizada = [r for r in recetas if r.get("id") != receta_id]
            user_data["recetas_disponibles"] = recetas_actualizada
            
            stats = user_data.setdefault("estadisticas", {})
            stats["total_recetas"] = len(recetas_actualizada)
            
            self._repository.save_user_data(handler_input, user_data)
            return receta_a_eliminar
        
        except Exception as e:
            logger.error(f"Error al eliminar receta: {e}", exc_info=True)
            return {"error": "error_interno"}


# ==============================
# Servicio de Filtrado y Paginación - Single Responsibility
# ==============================
class RecetaFilterService:
    """Servicio encargado del filtrado y paginación de recetas"""
    
    def __init__(self, repository: IUserRepository, state_service: RecetaStateService):
        self._repository = repository
        self._state_service = state_service
    
    def filtrar_recetas(self, handler_input, filtro_tipo: Optional[str], 
                       ingredientes: Optional[str]) -> Tuple[List[Dict], str]:
        """Filtra recetas según criterios y devuelve lista filtrada y título del filtro"""
        user_data = self._repository.get_user_data(handler_input)
        
        todas_recetas = user_data.get("recetas_disponibles", [])
        preparaciones = user_data.get("preparaciones_activas", [])
        
        # Sincronizar estados primero
        todas_recetas = self._state_service.sincronizar_estados(todas_recetas, preparaciones)
        
        recetas_filtradas = todas_recetas.copy()
        titulo_filtro = ""
        
        # Filtrar por ingredientes
        if ingredientes:
            recetas_filtradas = [
                r for r in recetas_filtradas 
                if r.get("ingredientes", "").lower() == ingredientes.lower()
            ]
            titulo_filtro = f" con {ingredientes}"
        
        # Filtrar por tipo/estado
        elif filtro_tipo:
            filtro_lower = filtro_tipo.lower()
            
            if filtro_lower in ["preparando", "en preparación"]:
                ids_preparando = [p.get("receta_id") for p in preparaciones]
                recetas_filtradas = [
                    r for r in recetas_filtradas 
                    if r.get("id") in ids_preparando
                ]
                titulo_filtro = " en preparación"
            
            elif filtro_lower in ["disponibles", "disponible"]:
                ids_preparando = [p.get("receta_id") for p in preparaciones]
                recetas_filtradas = [
                    r for r in recetas_filtradas 
                    if r.get("id") not in ids_preparando
                ]
                titulo_filtro = " disponibles"
        
        return recetas_filtradas, titulo_filtro
    
    @staticmethod
    def paginar_recetas(recetas_filtradas: List[Dict], 
                       pagina_actual: int) -> Dict[str, Any]:
        """Calcula la paginación y devuelve los datos relevantes"""
        total_recetas = len(recetas_filtradas)
        inicio = pagina_actual * RECETAS_POR_PAGINA
        fin = min(inicio + RECETAS_POR_PAGINA, total_recetas)
        
        recetas_pagina = recetas_filtradas[inicio:fin]
        
        return {
            "recetas_pagina": recetas_pagina,
            "inicio": inicio,
            "fin": fin,
            "total_filtradas": total_recetas,
            "quedan_mas": fin < total_recetas,
            "es_ultima_pagina": fin == total_recetas
        }


# ==============================
# Servicio de Preparaciones - Single Responsibility
# ==============================
class PreparacionService:
    """Servicio para gestión de preparaciones de recetas"""
    
    def __init__(self, repository: IUserRepository, search_service: RecetaSearchService):
        self._repository = repository
        self._search = search_service
    
    def registrar_preparacion(self, handler_input, nombre: str, 
                             nombre_persona: Optional[str]) -> Any:
        """Registra una nueva preparación de receta"""
        user_data = self._repository.get_user_data(handler_input)
        recetas = user_data.get("recetas_disponibles", [])
        preparaciones = user_data.get("preparaciones_activas", [])
        
        # Buscar receta
        receta = self._search.buscar_por_nombre_exacto(recetas, nombre)
        
        if not receta:
            return "no_encontrado"
        
        # Asegurar que la receta tiene ID
        if not receta.get("id"):
            receta["id"] = generar_id_unico()
            for r in recetas:
                if r.get("nombre") == receta.get("nombre"):
                    r["id"] = receta["id"]
                    break
        
        # Verificar si ya está en preparación
        preparacion_existente = next(
            (p for p in preparaciones if p.get("receta_id") == receta.get("id")), 
            None
        )
        
        if preparacion_existente:
            return "ya_preparando"
        
        # Crear nueva preparación
        nueva_preparacion = Preparacion(
            receta_id=receta["id"],
            nombre=receta["nombre"],
            nombre_persona=nombre_persona
        )
        
        preparaciones.append(nueva_preparacion.to_dict())
        
        # Actualizar estado de receta
        for r in recetas:
            if r.get("id") == receta.get("id"):
                r["estado"] = "preparando"
                r["total_preparaciones"] = r.get("total_preparaciones", 0) + 1
                break
        
        # Actualizar estadísticas
        stats = user_data.setdefault("estadisticas", {})
        stats["total_preparaciones"] = stats.get("total_preparaciones", 0) + 1
        
        user_data["recetas_disponibles"] = recetas
        user_data["preparaciones_activas"] = preparaciones
        
        self._repository.save_user_data(handler_input, user_data)
        
        return nueva_preparacion
    
    def registrar_completacion(self, handler_input, nombre: Optional[str] = None, 
                              id_preparacion: Optional[str] = None) -> Any:
        """Registra la completación de una preparación"""
        user_data = self._repository.get_user_data(handler_input)
        recetas = user_data.get("recetas_disponibles", [])
        preparaciones_activas = user_data.get("preparaciones_activas", [])
        historial = user_data.get("historial_preparaciones", [])
        
        if not preparaciones_activas:
            return "no_preparaciones"
        
        # Buscar preparación
        preparacion, indice = self._buscar_preparacion_activa(
            preparaciones_activas, nombre, id_preparacion
        )
        
        if not preparacion:
            return "no_encontrado"
        
        # Marcar como completada
        preparacion_finalizada = preparacion.copy()
        preparaciones_activas.pop(indice)
        
        preparacion_finalizada["fecha_completacion"] = datetime.now().isoformat()
        preparacion_finalizada["estado"] = "completada"
        
        # Verificar si se completó a tiempo
        fecha_limite = datetime.fromisoformat(preparacion_finalizada.get("fecha_limite"))
        preparacion_finalizada["completada_a_tiempo"] = datetime.now() <= fecha_limite
        
        historial.append(preparacion_finalizada)
        
        # Actualizar estado de receta
        for r in recetas:
            if r.get("id") == preparacion_finalizada.get("receta_id"):
                r["estado"] = "disponible"
                break
        
        # Actualizar estadísticas
        stats = user_data.setdefault("estadisticas", {})
        stats["total_completaciones"] = stats.get("total_completaciones", 0) + 1
        
        user_data["preparaciones_activas"] = preparaciones_activas
        user_data["historial_preparaciones"] = historial
        user_data["recetas_disponibles"] = recetas
        
        self._repository.save_user_data(handler_input, user_data)
        
        return preparacion_finalizada
    
    def obtener_preparaciones_activas_info(self, handler_input) -> Tuple[int, List[str]]:
        """Obtiene información sobre las preparaciones activas"""
        user_data = self._repository.get_user_data(handler_input)
        preparaciones = user_data.get("preparaciones_activas", [])
        
        num_preparando = len(preparaciones)
        ejemplos = [
            f"'{p.get('nombre')}' por {p.get('persona', 'un amigo')}" 
            for p in preparaciones[:3]
        ]
        
        return num_preparando, ejemplos
    
    def obtener_recetas_disponibles_info(self, handler_input) -> Tuple[int, List[str]]:
        """Obtiene información sobre recetas disponibles (no en preparación)"""
        user_data = self._repository.get_user_data(handler_input)
        recetas = user_data.get("recetas_disponibles", [])
        preparaciones = user_data.get("preparaciones_activas", [])
        
        ids_preparando = {p.get("receta_id") for p in preparaciones}
        disponibles = [r for r in recetas if r.get("id") and r.get("id") not in ids_preparando]
        
        num_disponibles = len(disponibles)
        ejemplos = [r.get("nombre") for r in disponibles[:2]]
        
        return num_disponibles, ejemplos
    
    @staticmethod
    def _buscar_preparacion_activa(preparaciones: List[Dict], 
                                   nombre: Optional[str], 
                                   id_preparacion: Optional[str]) -> Tuple[Optional[Dict], int]:
        """Busca una preparación activa por nombre o ID"""
        if not preparaciones:
            return None, -1
        
        # Buscar por ID
        if id_preparacion:
            for i, p in enumerate(preparaciones):
                if p.get("id") == id_preparacion:
                    return p, i
        
        # Buscar por nombre
        if nombre:
            nombre_lower = nombre.lower()
            for i, p in enumerate(preparaciones):
                if nombre_lower in p.get("nombre", "").lower():
                    return p, i
        
        return None, -1


# ==============================
# Servicio de Resúmenes e Información - Single Responsibility
# ==============================
class ResumenService:
    """Servicio para generar resúmenes y reportes"""
    
    def __init__(self, repository: IUserRepository):
        self._repository = repository
    
    def obtener_resumen_preparaciones(self, handler_input) -> Dict[str, Any]:
        """Genera resumen de preparaciones activas"""
        user_data = self._repository.get_user_data(handler_input)
        preparaciones_activas = user_data.get("preparaciones_activas", [])
        
        if not preparaciones_activas:
            return {
                "total": 0,
                "detalles": [],
                "hay_vencidas": False,
                "hay_proximas": False
            }
        
        total_preparaciones = len(preparaciones_activas)
        detalles = []
        hay_vencidas = False
        hay_proximas = False
        
        fecha_actual = datetime.now()
        
        for p in preparaciones_activas:
            detalle = f"'{p['nombre']}' está siendo preparada por {p.get('persona', 'alguien')}"
            
            try:
                fecha_limite = datetime.fromisoformat(p.get('fecha_limite'))
                dias_restantes = (fecha_limite - fecha_actual).days
                
                if dias_restantes < 0:
                    detalle += " (¡ya venció!)"
                    hay_vencidas = True
                elif dias_restantes == 0:
                    detalle += " (vence hoy)"
                    hay_proximas = True
                elif dias_restantes <= 2:
                    detalle += f" (vence en {dias_restantes} días)"
                    hay_proximas = True
            except Exception:
                detalle += " (fecha límite desconocida)"
            
            detalles.append(detalle)
        
        return {
            "total": total_preparaciones,
            "detalles": detalles,
            "hay_vencidas": hay_vencidas,
            "hay_proximas": hay_proximas
        }
    
    def obtener_resumen_historial(self, handler_input) -> Dict[str, Any]:
        """Genera resumen del historial de completaciones"""
        user_data = self._repository.get_user_data(handler_input)
        historial = user_data.get("historial_preparaciones", [])
        
        total = len(historial)
        
        if total == 0:
            return {
                "total": 0,
                "detalles_voz": [],
                "es_historial_completo": True
            }
        
        MAX_RECETAS_VOZ = 10
        
        if total <= MAX_RECETAS_VOZ:
            recetas_a_mostrar = historial
            es_historial_completo = True
        else:
            recetas_a_mostrar = historial[-5:]
            es_historial_completo = False
        
        detalles = []
        if not es_historial_completo:
            recetas_a_mostrar = reversed(recetas_a_mostrar)
        
        for h in recetas_a_mostrar:
            detalle = f"'{h.get('nombre', 'Sin nombre')}'"
            persona = h.get('persona', 'un amigo')
            if persona.lower() not in ['alguien', 'un amigo', 'desconocido']:
                detalle += f" que preparaste con {persona}"
            detalles.append(detalle)
        
        return {
            "total": total,
            "detalles_voz": detalles,
            "es_historial_completo": es_historial_completo
        }


# ==============================
# Servicio de Validación de Entrada - Single Responsibility
# ==============================
class InputValidationService:
    """Servicio para limpiar y normalizar valores de entrada del usuario"""
    
    @staticmethod
    def limpiar_y_normalizar_valor(valor: Optional[str], esperando: str) -> str:
        """Limpia y normaliza un valor según el tipo esperado"""
        if not valor:
            return valor
        
        valor = valor.lower().strip()
        no_se_options = ["no sé", "no se", "no lo sé", "no lo se"]
        
        if esperando == "ingredientes":
            default_value = "Desconocido"
            prefijo = "los ingredientes son"
            if valor in no_se_options or valor in ["no sé los ingredientes", "no se los ingredientes"]:
                return default_value
        
        elif esperando == "tipo":
            default_value = "Sin categoría"
            prefijo = "el tipo es"
            if valor in no_se_options or valor in ["no sé el tipo", "no se el tipo"]:
                return default_value
        
        else:  # nombre
            return valor.title()
        
        # Limpiar prefijos comunes
        if valor.startswith(f"{prefijo} "):
            return valor[len(f"{prefijo} "):].strip().title()
        elif valor.startswith("es "):
            return valor[3:].strip().title()
        
        return valor.title()
