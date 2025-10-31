from database import DatabaseManager
from phrases import PhrasesManager 
from models import generar_id_unico, Receta, Preparacion
from datetime import datetime, timedelta
from config import RECETAS_POR_PAGINA

def buscar_receta_por_nombre(recetas, nombre_buscado):
    if not nombre_buscado:
        return []
    nombre_lower = nombre_buscado.lower()
    resultados = []
    
    for receta in recetas:
        receta_nombre_lower = receta.get("nombre", "").lower()
        if receta_nombre_lower == nombre_lower:
            resultados.insert(0, receta) 
        elif nombre_lower in receta_nombre_lower:
            resultados.append(receta)
    return resultados

def buscar_receta_por_nombre_exacto(recetas, nombre):
    if not nombre:
        return None
    nombre_lower = nombre.lower()
    for receta in recetas:
        if receta.get("nombre", "").lower() == nombre_lower:
            return receta
    return None

class RecetarioService:
    @staticmethod
    def agregar_receta(handler_input, nombre, ingredientes, tipo):
        
        user_data = DatabaseManager.get_user_data(handler_input)
        recetas = user_data.get("recetas_disponibles", [])
        
        if any(receta.get("nombre", "").lower() == nombre.lower() for receta in recetas):
            return False

        nueva_receta = Receta(nombre=nombre, ingredientes=ingredientes, tipo=tipo)
        
        recetas.append(nueva_receta.to_dict())
        stats = user_data.setdefault("estadisticas", {})
        stats["total_recetas"] = len(recetas)
        
        DatabaseManager.save_user_data(handler_input, user_data)
        
        return nueva_receta
    
    @staticmethod
    def limpiar_y_normalizar_valor(valor, esperando):
        if not valor:
            return valor

        valor = valor.lower().strip()
        no_se_options = ["no sé", "no se", "no lo sé", "no lo se"]
        
        if esperando == "ingredientes":
            default_value = "Desconocido"
            prefijo = "los ingredientes son"
            if valor in no_se_options or valor == "no sé los ingredientes" or valor == "no se los ingredientes":
                return default_value
        elif esperando == "tipo":
            default_value = "Sin categoría"
            prefijo = "el tipo es"
            if valor in no_se_options or valor == "no sé el tipo" or valor == "no se el tipo":
                return default_value
        else:
            return valor.title()
        if valor.startswith(f"{prefijo} "):
            return valor[len(f"{prefijo} "):].strip().title()
        elif valor.startswith("es "):
            return valor[3:].strip().title()
        
        return valor.title()
        
    @staticmethod
    def get_recetas(handler_input):
        """Devuelve la lista completa de recetas del usuario."""
        user_data = DatabaseManager.get_user_data(handler_input)
        return user_data.get("recetas_disponibles", [])

    @staticmethod
    def sincronizar_y_filtrar_recetas(handler_input, filtro_tipo, ingredientes):
        """
        Sincroniza el estado de las preparaciones, guarda los datos y luego filtra.
        Retorna: lista de recetas filtradas, el título del filtro aplicado.
        """
        user_data = DatabaseManager.get_user_data(handler_input)

        todas_recetas = user_data.get("recetas_disponibles", [])
        preparaciones = user_data.get("preparaciones_activas", [])
        recetas_filtradas = todas_recetas.copy()
        titulo_filtro = ""
        
        if ingredientes:
            recetas_filtradas = [l for l in recetas_filtradas if l.get("ingredientes", "").lower() == ingredientes.lower()]
            titulo_filtro = f" con {ingredientes}"
        elif filtro_tipo:
            filtro_tipo_lower = filtro_tipo.lower()
            if filtro_tipo_lower in ["preparando", "en preparación"]:
                ids_preparando = [p.get("receta_id") for p in preparaciones]
                recetas_filtradas = [l for l in recetas_filtradas if l.get("id") in ids_preparando]
                titulo_filtro = " en preparación"
            elif filtro_tipo_lower in ["disponibles", "disponible"]:
                ids_preparando = [p.get("receta_id") for p in preparaciones]
                recetas_filtradas = [l for l in recetas_filtradas if l.get("id") not in ids_preparando]
                titulo_filtro = " disponibles"
                
        return recetas_filtradas, titulo_filtro

    @staticmethod
    def obtener_pagina_recetas(recetas_filtradas, pagina_actual):
        """Calcula la paginación y devuelve los datos relevantes."""
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
        
    @staticmethod
    def registrar_preparacion(handler_input, nombre, nombre_persona):
        """Busca la receta, valida el estado y registra la preparación. Retorna Preparacion, o cadena de error."""
        user_data = DatabaseManager.get_user_data(handler_input)
        recetas = user_data.get("recetas_disponibles", [])
        preparaciones_dicts = user_data.get("preparaciones_activas", [])
        
        receta = buscar_receta_por_nombre_exacto(recetas, nombre)
        
        if not receta:
            return "no_encontrado"

        if not receta.get("id"):
            receta["id"] = generar_id_unico()
            for l in recetas:
                if l.get("nombre") == receta.get("nombre"):
                    l["id"] = receta["id"]
                    break
        preparacion_existente = next((p for p in preparaciones_dicts if p.get("receta_id") == receta.get("id")), None)

        if preparacion_existente:
            return "ya_preparando"
        nueva_preparacion = Preparacion(
            receta_id=receta["id"], 
            nombre=receta["nombre"], 
            nombre_persona=nombre_persona
        )
        preparaciones_dicts.append(nueva_preparacion.to_dict())
        for l in recetas:
            if l.get("id") == receta.get("id"):
                l["estado"] = "preparando"
                l["total_preparaciones"] = l.get("total_preparaciones", 0) + 1
                break
                
        stats = user_data.setdefault("estadisticas", {})
        stats["total_preparaciones"] = stats.get("total_preparaciones", 0) + 1

        user_data["recetas_disponibles"] = recetas
        user_data["preparaciones_activas"] = preparaciones_dicts
        
        DatabaseManager.save_user_data(handler_input, user_data)
        
        return nueva_preparacion
        
    @staticmethod
    def get_recetas_disponibles_info(handler_input):
        user_data = DatabaseManager.get_user_data(handler_input)
        recetas = user_data.get("recetas_disponibles", [])
        preparaciones = user_data.get("preparaciones_activas", [])
        
        ids_preparando = {p.get("receta_id") for p in preparaciones}
        disponibles = [l for l in recetas if l.get("id") and l.get("id") not in ids_preparando]
        
        num_disponibles = len(disponibles)
        ejemplos = [l.get("nombre") for l in disponibles[:2]]

        return num_disponibles, ejemplos
    
    @staticmethod
    def buscar_recetas(handler_input, nombre):
        user_data = DatabaseManager.get_user_data(handler_input)
        recetas = user_data.get("recetas_disponibles", [])
        recetas_encontradas = buscar_receta_por_nombre(recetas, nombre)
        return recetas_encontradas
        
    @staticmethod
    def buscar_preparacion_activa(preparaciones_dicts, nombre, id_preparacion):
        if not preparaciones_dicts:
            return None, -1
        preparacion_encontrada = None
        indice = -1
        if id_preparacion:
            for i, p in enumerate(preparaciones_dicts):
                if p.get("id") == id_preparacion:
                    return p, i
        if nombre:
            nombre_lower = nombre.lower()
            for i, p in enumerate(preparaciones_dicts):
                if nombre_lower in p.get("nombre", "").lower():
                    return p, i
        return None, -1

    @staticmethod
    def registrar_completacion(handler_input, nombre=None, id_preparacion=None):
        user_data = DatabaseManager.get_user_data(handler_input)
        recetas = user_data.get("recetas_disponibles", [])
        preparaciones_activas = user_data.get("preparaciones_activas", [])
        historial_preparaciones = user_data.get("historial_preparaciones", [])
        if not preparaciones_activas:
            return "no_preparaciones"
        preparacion_a_completar, indice = RecetarioService.buscar_preparacion_activa(
            preparaciones_activas, nombre, id_preparacion
        )

        if not preparacion_a_completar:
            return "no_encontrado"
        preparacion_finalizada = preparacion_a_completar.copy() 
        
        preparaciones_activas.pop(indice) 
        
        preparacion_finalizada["fecha_completacion"] = datetime.now().isoformat()
        preparacion_finalizada["estado"] = "completada"
        
        fecha_limite = datetime.fromisoformat(preparacion_finalizada.get("fecha_limite"))
        preparacion_finalizada["completada_a_tiempo"] = datetime.now() <= fecha_limite

        historial_preparaciones.append(preparacion_finalizada)

        for l in recetas:
            if l.get("id") == preparacion_finalizada.get("receta_id"):
                l["estado"] = "disponible"
                break
        stats = user_data.setdefault("estadisticas", {})
        stats["total_completaciones"] = stats.get("total_completaciones", 0) + 1

        user_data["preparaciones_activas"] = preparaciones_activas
        user_data["historial_preparaciones"] = historial_preparaciones
        DatabaseManager.save_user_data(handler_input, user_data)

        return preparacion_finalizada

    @staticmethod
    def get_preparaciones_activas_info(handler_input):
        user_data = DatabaseManager.get_user_data(handler_input)
        preparaciones = user_data.get("preparaciones_activas", [])
        
        num_preparando = len(preparaciones)
        ejemplos = [
            f"'{p.get('nombre')}' por {p.get('persona', 'un amigo')}" 
            for p in preparaciones[:3]
        ]

        return num_preparando, ejemplos
        
    @staticmethod
    def obtener_resumen_preparaciones(handler_input):
        user_data = DatabaseManager.get_user_data(handler_input)
        preparaciones_activas = user_data.get("preparaciones_activas", [])
        
        if not preparaciones_activas:
            return {
                "total": 0,
                "detalles": [],
                "hay_vencidas": False,
                "hay_proximas": False
            }

        total_preparaciones = len(preparaciones_activas)
        detalles_analizados = []
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
            except:
                detalle += " (fecha límite desconocida)"
            
            detalles_analizados.append(detalle)
            
        return {
            "total": total_preparaciones,
            "detalles": detalles_analizados,
            "hay_vencidas": hay_vencidas,
            "hay_proximas": hay_proximas
        }
        
    @staticmethod
    def obtener_resumen_historial(handler_input):
        user_data = DatabaseManager.get_user_data(handler_input)
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
        
    @staticmethod
    def eliminar_receta(handler_input, nombre):
        user_data = DatabaseManager.get_user_data(handler_input)
        recetas = user_data.get("recetas_disponibles", [])
        preparaciones_activas = user_data.get("preparaciones_activas", [])
        receta_a_eliminar = buscar_receta_por_nombre_exacto(recetas, nombre)
        
        if not receta_a_eliminar:
            return "no_encontrado"
            
        receta_id = receta_a_eliminar.get("id")
        if any(p.get("receta_id") == receta_id for p in preparaciones_activas):
            return "esta_preparando"
        try:
            recetas_actualizada = [l for l in recetas if l.get("id") != receta_id]
            user_data["recetas_disponibles"] = recetas_actualizada
            
            stats = user_data.setdefault("estadisticas", {})
            stats["total_recetas"] = len(recetas_actualizada)
            
            DatabaseManager.save_user_data(handler_input, user_data)
            
            return receta_a_eliminar
        except Exception as e:
            logger.error(f"Error al eliminar la receta {nombre}: {e}", exc_info=True)
            return "error_interno"