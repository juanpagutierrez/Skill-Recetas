"""
Capa de compatibilidad para servicios - Facade Pattern
Mantiene la interfaz existente mientras delega a servicios especializados (SOLID).
"""
import logging
from database import DatabaseManager
from services_domain import (
    RecetaSearchService,
    RecetaStateService, 
    RecetaService,
    RecetaFilterService,
    PreparacionService,
    ResumenService,
    InputValidationService
)

logger = logging.getLogger(__name__)


# ==============================
# Funciones de utilidad para búsqueda - Mantienen compatibilidad
# ==============================
def buscar_receta_por_nombre(recetas, nombre_buscado):
    """Función de compatibilidad - delega a RecetaSearchService"""
    return RecetaSearchService.buscar_por_nombre(recetas, nombre_buscado)


def buscar_receta_por_nombre_exacto(recetas, nombre):
    """Función de compatibilidad - delega a RecetaSearchService"""
    return RecetaSearchService.buscar_por_nombre_exacto(recetas, nombre)


# ==============================
# RecetarioService - Facade Pattern para mantener compatibilidad
# Delega a servicios especializados (cumple SOLID)
# ==============================
class RecetarioService:
    """
    Facade que mantiene la interfaz original pero delega a servicios especializados.
    Esto permite migrar gradualmente sin romper el código existente.
    """
    
    # Servicios especializados (inyección de dependencias)
    _receta_service = None
    _preparacion_service = None
    _filter_service = None
    _resumen_service = None
    _search_service = RecetaSearchService()
    _state_service = RecetaStateService()
    _validation_service = InputValidationService()
    
    @classmethod
    def _ensure_services_initialized(cls):
        """Inicializa servicios si no están creados"""
        if cls._receta_service is None:
            # Obtener repositorio del DatabaseManager
            repository = DatabaseManager._repository
            if repository is None:
                raise RuntimeError("DatabaseManager no inicializado")
            
            cls._receta_service = RecetaService(repository, cls._search_service)
            cls._preparacion_service = PreparacionService(repository, cls._search_service)
            cls._filter_service = RecetaFilterService(repository, cls._state_service)
            cls._resumen_service = ResumenService(repository)
    
    @classmethod
    def agregar_receta(cls, handler_input, nombre, ingredientes, tipo):
        """Delega a RecetaService"""
        cls._ensure_services_initialized()
        return cls._receta_service.agregar_receta(handler_input, nombre, ingredientes, tipo)
    
    @classmethod
    def limpiar_y_normalizar_valor(cls, valor, esperando):
        """Delega a InputValidationService"""
        return cls._validation_service.limpiar_y_normalizar_valor(valor, esperando)
    
    @classmethod
    def get_recetas(cls, handler_input):
        """Delega a RecetaService"""
        cls._ensure_services_initialized()
        return cls._receta_service.obtener_recetas(handler_input)
    
    @classmethod
    def sincronizar_y_filtrar_recetas(cls, handler_input, filtro_tipo, ingredientes):
        """Delega a RecetaFilterService"""
        cls._ensure_services_initialized()
        return cls._filter_service.filtrar_recetas(handler_input, filtro_tipo, ingredientes)
    
    @classmethod
    def obtener_pagina_recetas(cls, recetas_filtradas, pagina_actual):
        """Delega a RecetaFilterService"""
        return RecetaFilterService.paginar_recetas(recetas_filtradas, pagina_actual)
    
    @classmethod
    def registrar_preparacion(cls, handler_input, nombre, nombre_persona):
        """Delega a PreparacionService"""
        cls._ensure_services_initialized()
        return cls._preparacion_service.registrar_preparacion(handler_input, nombre, nombre_persona)
    
    @classmethod
    def get_recetas_disponibles_info(cls, handler_input):
        """Delega a PreparacionService"""
        cls._ensure_services_initialized()
        return cls._preparacion_service.obtener_recetas_disponibles_info(handler_input)
    
    @classmethod
    def buscar_recetas(cls, handler_input, nombre):
        """Delega a RecetaService"""
        cls._ensure_services_initialized()
        return cls._receta_service.buscar_recetas(handler_input, nombre)
    
    @classmethod
    def registrar_completacion(cls, handler_input, nombre, id_preparacion):
        """Delega a PreparacionService"""
        cls._ensure_services_initialized()
        return cls._preparacion_service.registrar_completacion(handler_input, nombre, id_preparacion)
    
    @classmethod
    def get_preparaciones_activas_info(cls, handler_input):
        """Delega a PreparacionService"""
        cls._ensure_services_initialized()
        return cls._preparacion_service.obtener_preparaciones_activas_info(handler_input)
    
    @classmethod
    def obtener_resumen_preparaciones(cls, handler_input):
        """Delega a ResumenService"""
        cls._ensure_services_initialized()
        return cls._resumen_service.obtener_resumen_preparaciones(handler_input)
    
    @classmethod
    def obtener_resumen_historial(cls, handler_input):
        """Delega a ResumenService"""
        cls._ensure_services_initialized()
        return cls._resumen_service.obtener_resumen_historial(handler_input)
    
    @classmethod
    def eliminar_receta(cls, handler_input, nombre):
        """Delega a RecetaService"""
        cls._ensure_services_initialized()
        resultado = cls._receta_service.eliminar_receta(handler_input, nombre)
        
        # Adaptar respuesta para compatibilidad
        if resultado is None:
            return "no_encontrado"
        elif isinstance(resultado, dict) and resultado.get("error"):
            return resultado["error"]
        else:
            return resultado
