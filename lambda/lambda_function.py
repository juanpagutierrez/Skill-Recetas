import os
import logging
from datetime import datetime
import random
import uuid

import ask_sdk_core.utils as ask_utils
from ask_sdk_core.skill_builder import CustomSkillBuilder
from ask_sdk_core.dispatch_components import AbstractRequestHandler, AbstractExceptionHandler
from ask_sdk_s3.adapter import S3Adapter
from ask_sdk_core.handler_input import HandlerInput

import phrases
from phrases import PhrasesManager
from config import USE_FAKE_S3, S3_PERSISTENCE_BUCKET, RECETAS_POR_PAGINA
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List

# Importar componentes SOLID
from database import (
    FakeS3Adapter, 
    InMemoryCacheStrategy, 
    DynamoDBCacheStrategy, 
    UserRepository,
    DatabaseManager
)
from services_domain import RecetaStateService
from services import RecetarioService
from models import Preparacion, RecetaBuilder, PreparacionBuilder

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ==============================
# Inicializar persistence adapter y repositorio (Dependency Injection)
# ==============================
if USE_FAKE_S3:
    persistence_adapter = FakeS3Adapter()
else:
    s3_bucket = S3_PERSISTENCE_BUCKET
    if not s3_bucket:
        raise RuntimeError("S3_PERSISTENCE_BUCKET es requerido cuando USE_FAKE_S3=false")
    logger.info(f"🪣 Usando S3Adapter con bucket: {s3_bucket}")
    persistence_adapter = S3Adapter(bucket_name=s3_bucket)

# Inicializar estrategias de cache
memory_cache = InMemoryCacheStrategy()
ddb_cache = DynamoDBCacheStrategy() if os.getenv("ENABLE_DDB_CACHE", "false").lower() == "true" else None

# Crear repositorio con inyección de dependencias
user_repository = UserRepository(
    persistence_adapter=persistence_adapter,
    memory_cache=memory_cache,
    ddb_cache=ddb_cache
)

# Inicializar DatabaseManager con el repositorio (Facade Pattern)
DatabaseManager.initialize(user_repository)

sb = CustomSkillBuilder(persistence_adapter=persistence_adapter)

# ==============================
# Helpers
# ==============================
def generar_id_unico():
    """Genera un ID único para recetas y preparaciones"""
    return str(uuid.uuid4())[:8]

def sincronizar_estados_recetas(user_data):
    """Sincroniza los estados de las recetas basándose en las preparaciones activas"""
    recetas = user_data.get("recetas_disponibles", [])
    preparaciones = user_data.get("preparaciones_activas", [])
    
    # Delegar a RecetaStateService (SOLID - Single Responsibility)
    recetas_sincronizadas = RecetaStateService.sincronizar_estados(recetas, preparaciones)
    user_data["recetas_disponibles"] = recetas_sincronizadas
    
    return user_data

def generar_id_preparacion():
    """Genera un ID único para preparaciones"""
    return f"PREP-{datetime.now().strftime('%Y%m%d')}-{generar_id_unico()}"

# ==============================
# Strategy Pattern - Estrategias de respuesta
# ==============================
class ResponseStrategy(ABC):
    """Estrategia base para generar respuestas"""
    
    @abstractmethod
    def generate_response(self, handler_input, context: Dict[str, Any]) -> Dict[str, str]:
        """Genera una respuesta basada en el contexto"""
        pass

class WelcomeResponseStrategy(ResponseStrategy):
    """Estrategia para respuestas de bienvenida"""
    
    def generate_response(self, handler_input, context: Dict[str, Any]) -> Dict[str, str]:
        user_data = context.get('user_data', {})
        total_recetas = context.get('total_recetas', 0)
        preparaciones_activas = context.get('preparaciones_activas', 0)
        usuario_frecuente = context.get('usuario_frecuente', False)
        
        speak_output = PhrasesManager.get_welcome_message(
            user_data, total_recetas, preparaciones_activas, usuario_frecuente
        )
        reprompt_output = "¿Quieres que te recuerde los comandos principales o añadir una receta?"
        
        return {
            'speak_output': speak_output,
            'reprompt_output': reprompt_output
        }

class ErrorResponseStrategy(ResponseStrategy):
    """Estrategia para respuestas de error"""
    
    def generate_response(self, handler_input, context: Dict[str, Any]) -> Dict[str, str]:
        error_type = context.get('error_type', 'general')
        
        if error_type == 'no_recetas':
            speak_output = "Aún no tienes recetas en tu recetario. ¿Te gustaría agregar la primera? Solo di: agrega una receta."
            reprompt_output = "¿Quieres agregar tu primera receta?"
        elif error_type == 'no_encontrado':
            nombre = context.get('nombre', '')
            speak_output = f"No encontré '{nombre}' en tu recetario. {PhrasesManager.get_algo_mas()}"
            reprompt_output = PhrasesManager.get_preguntas_que_hacer()
        else:
            speak_output = "Hubo un problema. ¿Intentamos de nuevo?"
            reprompt_output = "¿Qué deseas hacer?"
            
        return {
            'speak_output': speak_output,
            'reprompt_output': reprompt_output
        }

# ==============================
# Factory Pattern - Factory de Handlers
# ==============================
class HandlerFactory:
    """Factory para crear handlers con patrones aplicados"""
    
    _response_strategies = {
        'welcome': WelcomeResponseStrategy(),
        'error': ErrorResponseStrategy()
    }
    
    @classmethod
    def get_response_strategy(cls, strategy_type: str) -> ResponseStrategy:
        """Obtiene una estrategia de respuesta"""
        return cls._response_strategies.get(strategy_type, cls._response_strategies['error'])
    
    @classmethod
    def create_builder_based_handler(cls, handler_type: str):
        """Crea handlers que usan Builder pattern para construir objetos"""
        if handler_type == 'receta':
            return RecetaBuilderHandler()
        elif handler_type == 'preparacion':
            return PreparacionBuilderHandler()
        return None

# ==============================
# Template Method Pattern - Handler base
# ==============================
class BaseSkillHandler(AbstractRequestHandler):
    """Handler base que implementa Template Method pattern"""
    
    def handle(self, handler_input):
        """Template method que define el flujo común"""
        try:
            # 1. Preparar contexto
            context = self.prepare_context(handler_input)
            
            # 2. Validar entrada
            validation_result = self.validate_input(handler_input, context)
            if not validation_result['valid']:
                return self.create_error_response(handler_input, validation_result)
            
            # 3. Procesar lógica específica
            result = self.process_business_logic(handler_input, context)
            
            # 4. Generar respuesta
            return self.generate_response(handler_input, result)
            
        except Exception as e:
            logger.error(f"Error en {self.__class__.__name__}: {e}", exc_info=True)
            return self.handle_error(handler_input, e)
    
    @abstractmethod
    def prepare_context(self, handler_input) -> Dict[str, Any]:
        """Prepara el contexto necesario - debe ser implementado"""
        pass
    
    def validate_input(self, handler_input, context: Dict[str, Any]) -> Dict[str, Any]:
        """Valida la entrada - puede ser sobrescrito"""
        return {'valid': True}
    
    @abstractmethod
    def process_business_logic(self, handler_input, context: Dict[str, Any]) -> Dict[str, Any]:
        """Procesa la lógica de negocio específica - debe ser implementado"""
        pass
    
    def generate_response(self, handler_input, result: Dict[str, Any]):
        """Genera la respuesta final - puede ser sobrescrito"""
        speak_output = result.get('speak_output', 'Operación completada.')
        reprompt_output = result.get('reprompt_output', '¿Qué más deseas hacer?')
        
        return (
            handler_input.response_builder
                .speak(speak_output)
                .ask(reprompt_output)
                .response
        )
    
    def create_error_response(self, handler_input, validation_result: Dict[str, Any]):
        """Crea respuesta de error de validación"""
        error_strategy = HandlerFactory.get_response_strategy('error')
        context = {'error_type': validation_result.get('error_type', 'general')}
        response_data = error_strategy.generate_response(handler_input, context)
        
        return (
            handler_input.response_builder
                .speak(response_data['speak_output'])
                .ask(response_data['reprompt_output'])
                .response
        )
    
    def handle_error(self, handler_input, error: Exception):
        """Maneja errores generales"""
        return (
            handler_input.response_builder
                .speak("Hubo un problema. ¿Intentamos de nuevo?")
                .ask("¿Qué deseas hacer?")
                .response
        )

# ==============================
# Handlers específicos usando patrones
# ==============================
class RecetaBuilderHandler(BaseSkillHandler):
    """Handler que usa Builder pattern para crear recetas"""
    
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("CrearRecetaConBuilderIntent")(handler_input)
    
    def prepare_context(self, handler_input) -> Dict[str, Any]:
        return {
            'nombre': ask_utils.get_slot_value(handler_input, "nombre"),
            'ingredientes': ask_utils.get_slot_value(handler_input, "ingredientes"),
            'tipo': ask_utils.get_slot_value(handler_input, "tipo")
        }
    
    def validate_input(self, handler_input, context: Dict[str, Any]) -> Dict[str, Any]:
        if not context.get('nombre'):
            return {
                'valid': False,
                'error_type': 'missing_name',
                'message': 'Necesito el nombre de la receta'
            }
        return {'valid': True}
    
    def process_business_logic(self, handler_input, context: Dict[str, Any]) -> Dict[str, Any]:
        # Usar Builder pattern para crear la receta
        receta = (RecetaBuilder()
                  .with_nombre(context['nombre'])
                  .with_ingredientes(context.get('ingredientes'))
                  .with_tipo(context.get('tipo'))
                  .build())
        
        # Guardar usando el servicio
        user_data = DatabaseManager.get_user_data(handler_input)
        recetas = user_data.get("recetas_disponibles", [])
        recetas.append(receta.to_dict())
        user_data["recetas_disponibles"] = recetas
        DatabaseManager.save_user_data(handler_input, user_data)
        
        return {
            'speak_output': f"¡Excelente! He creado '{receta.nombre}' usando el patrón Builder. {PhrasesManager.get_algo_mas()}",
            'reprompt_output': PhrasesManager.get_preguntas_que_hacer()
        }

class PreparacionBuilderHandler(BaseSkillHandler):
    """Handler que usa Builder pattern para crear preparaciones"""
    
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("CrearPreparacionConBuilderIntent")(handler_input)
    
    def prepare_context(self, handler_input) -> Dict[str, Any]:
        return {
            'receta_id': ask_utils.get_slot_value(handler_input, "receta_id"),
            'nombre_receta': ask_utils.get_slot_value(handler_input, "nombre_receta"),
            'nombre_persona': ask_utils.get_slot_value(handler_input, "nombre_persona"),
            'dias': int(ask_utils.get_slot_value(handler_input, "dias") or 7)
        }
    
    def validate_input(self, handler_input, context: Dict[str, Any]) -> Dict[str, Any]:
        if not context.get('receta_id') or not context.get('nombre_receta'):
            return {
                'valid': False,
                'error_type': 'missing_recipe_info',
                'message': 'Necesito la información de la receta'
            }
        return {'valid': True}
    
    def process_business_logic(self, handler_input, context: Dict[str, Any]) -> Dict[str, Any]:
        # Usar Builder pattern para crear la preparación
        preparacion = (PreparacionBuilder()
                      .for_receta(context['receta_id'], context['nombre_receta'])
                      .by_person(context.get('nombre_persona'))
                      .with_duration(context['dias'])
                      .build())
        
        # Guardar usando el servicio
        user_data = DatabaseManager.get_user_data(handler_input)
        preparaciones = user_data.get("preparaciones_activas", [])
        preparaciones.append(preparacion.to_dict())
        user_data["preparaciones_activas"] = preparaciones
        DatabaseManager.save_user_data(handler_input, user_data)
        
        return {
            'speak_output': f"¡Perfecto! He registrado la preparación de '{preparacion.nombre}' usando Builder pattern. {PhrasesManager.get_algo_mas()}",
            'reprompt_output': PhrasesManager.get_preguntas_que_hacer()
        }

# ==============================
# Handlers originales (manteniendo compatibilidad)
# ==============================

class LaunchRequestHandler(AbstractRequestHandler):
    """Handler de bienvenida que usa Strategy pattern para respuestas"""
    
    def can_handle(self, handler_input):
        return ask_utils.is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):
        user_data = DatabaseManager.get_user_data(handler_input)
        user_data = sincronizar_estados_recetas(user_data)

        recetas = user_data.get("recetas_disponibles", [])
        total_recetas = len(recetas)
        preparaciones_activas = len(user_data.get("preparaciones_activas", []))
        usuario_frecuente = user_data.get("usuario_frecuente", False)
        
        # Usar Strategy pattern para generar respuesta
        welcome_strategy = HandlerFactory.get_response_strategy('welcome')
        context = {
            'user_data': user_data,
            'total_recetas': total_recetas,
            'preparaciones_activas': preparaciones_activas,
            'usuario_frecuente': usuario_frecuente
        }
        response_data = welcome_strategy.generate_response(handler_input, context)

        if not usuario_frecuente:
            user_data["usuario_frecuente"] = True
            DatabaseManager.save_user_data(handler_input, user_data) 
            
        return (
            handler_input.response_builder
                .speak(response_data['speak_output'])
                .ask(response_data['reprompt_output'])
                .response
        )

class AgregarRecetaIntentHandler(AbstractRequestHandler):
    """Handler para agregar recetas - Enfocado en el manejo manual del diálogo."""
    def can_handle(self, handler_input: HandlerInput):
        return ask_utils.is_intent_name("AgregarRecetaIntent")(handler_input)

    def handle(self, handler_input: HandlerInput):
        session_attrs = handler_input.attributes_manager.session_attributes
        
        # --- Lógica de recuperación de Slots y Sesión (mantienes tu flujo) ---
        nombre = ask_utils.get_slot_value(handler_input, "nombre")
        ingredientes = ask_utils.get_slot_value(handler_input, "ingredientes")
        tipo = ask_utils.get_slot_value(handler_input, "tipo")
        
        if session_attrs.get("agregando_receta"):
            nombre = nombre or session_attrs.get("nombre_temp")
            ingredientes = ingredientes or session_attrs.get("ingredientes_temp")
            tipo = tipo or session_attrs.get("tipo_temp")
            
        # PASO 1: Pedir nombre (y guardar temporalmente)
        if not nombre:
            session_attrs["agregando_receta"] = True
            session_attrs["esperando"] = "nombre"
            return (
                handler_input.response_builder
                    .speak("¡Perfecto! Vamos a agregar una receta. ¿Cuál es el nombre?")
                    .ask("¿Cuál es el nombre de la receta?")
                    .response
            )
        session_attrs["nombre_temp"] = nombre
        session_attrs["agregando_receta"] = True
        
        # PASO 2: Pedir ingredientes (y guardar temporalmente)
        if not ingredientes:
            session_attrs["esperando"] = "ingredientes"
            return (
                handler_input.response_builder
                    .speak(f"¡'{nombre}' suena deliciosa! ¿Cuáles son los ingredientes principales? Si no los sabes, di: no sé.")
                    .ask("¿Cuáles son los ingredientes?")
                    .response
            )
        session_attrs["ingredientes_temp"] = ingredientes
        
        # PASO 3: Pedir tipo (y guardar temporalmente)
        if not tipo:
            session_attrs["esperando"] = "tipo"
            ingredientes_text = f" con {ingredientes}" if ingredientes and ingredientes.lower() not in ["no sé", "no se"] else ""
            return (
                handler_input.response_builder
                    .speak(f"Casi listo con '{nombre}'{ingredientes_text}. ¿De qué tipo de comida es? Si no sabes, di: no sé.")
                    .ask("¿De qué tipo es la receta?")
                    .response
            )
        session_attrs["tipo_temp"] = tipo

        nueva_receta = RecetarioService.agregar_receta(handler_input, nombre, ingredientes, tipo)
        handler_input.attributes_manager.session_attributes = {}
        
        if nueva_receta is False:
            speak_output = f"'{nombre}' ya está en tu recetario. {PhrasesManager.get_algo_mas()}"
            reprompt = PhrasesManager.get_preguntas_que_hacer()
        else:
            confirmacion = PhrasesManager.get_confirmaciones()
            
            ingredientes_text = f" con {nueva_receta.ingredientes}" if nueva_receta.ingredientes != "Desconocido" else ""
            tipo_text = f", tipo {nueva_receta.tipo}" if nueva_receta.tipo != "Sin categoría" else ""
            
            speak_output = (
                f"{confirmacion}! He agregado '{nueva_receta.nombre}'{ingredientes_text}{tipo_text}. "
                f"Ahora tienes {len(RecetarioService.get_recetas(handler_input))} recetas en tu recetario. "
                f"{PhrasesManager.get_algo_mas()}"
            )
            reprompt = PhrasesManager.get_preguntas_que_hacer()

        return (
            handler_input.response_builder
                .speak(speak_output)
                .ask(reprompt)
                .response
        )


class ContinuarAgregarHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput):
        session_attrs = handler_input.attributes_manager.session_attributes
        return (session_attrs.get("agregando_receta") and 
                not ask_utils.is_intent_name("AgregarRecetaIntent")(handler_input) and
                not ask_utils.is_intent_name("AMAZON.CancelIntent")(handler_input) and
                not ask_utils.is_intent_name("AMAZON.StopIntent")(handler_input))
    
    def handle(self, handler_input: HandlerInput):
        session_attrs = handler_input.attributes_manager.session_attributes
        esperando = session_attrs.get("esperando")
        valor = None
        request = handler_input.request_envelope.request
        intent_name = request.intent.name if hasattr(request, 'intent') and request.intent else None
        
        if intent_name == "RespuestaGeneralIntent":
            valor = ask_utils.get_slot_value(handler_input, "respuesta")
        
        if not valor and intent_name and hasattr(request.intent, 'slots') and request.intent.slots:
            for slot_name, slot in request.intent.slots.items():
                if slot and hasattr(slot, 'value') and slot.value:
                    valor = slot.value
                    break
        
        # 2. Manejo de Malinterpretación de Intents (Workaround, se mantiene aquí)
        if not valor and intent_name in ["LimpiarCacheIntent", "SiguientePaginaIntent", 
                                        "ListarRecetasIntent", "BuscarRecetaIntent"]:
            # Usar frases genéricas para pedir repetición
            if esperando == "ingredientes":
                speak = "No entendí bien. Por favor di: 'los ingredientes son' seguido de los ingredientes. O di: no sé los ingredientes."
                reprompt = "¿Cuáles son los ingredientes? Di: 'los ingredientes son' y los ingredientes."
            elif esperando == "tipo":
                speak = "No entendí bien. Por favor di: 'el tipo es' seguido del tipo de comida. O di: no sé el tipo."
                reprompt = "¿De qué tipo es? Di: 'el tipo es' y el tipo de comida."
            else: # Nombre
                speak = "No entendí bien. Por favor di: 'el nombre es' seguido del nombre de la receta."
                reprompt = "¿Cuál es el nombre? Di: 'el nombre es' y el nombre."
            return handler_input.response_builder.speak(speak).ask(reprompt).response

        # 3. Procesar y Avanzar el Flujo (Lógica central)
        if esperando == "nombre":
            # Si el valor no es nulo, normalizar y avanzar.
            if valor:
                valor_limpio = RecetarioService.limpiar_y_normalizar_valor(valor, "nombre")
                session_attrs["nombre_temp"] = valor_limpio
                session_attrs["esperando"] = "ingredientes"
                speak = f"¡'{valor_limpio}' suena deliciosa! ¿Cuáles son los ingredientes principales? Si no los sabes, di: no sé los ingredientes."
                return handler_input.response_builder.speak(speak).ask("¿Cuáles son los ingredientes?").response
            else:
                # No se capturó valor
                speak = "No entendí el nombre. Por favor di: 'el nombre es' seguido del nombre de la receta."
                return handler_input.response_builder.speak(speak).ask("¿Cuál es el nombre de la receta?").response
        
        elif esperando == "ingredientes":
            valor_limpio = RecetarioService.limpiar_y_normalizar_valor(valor, "ingredientes")
            session_attrs["ingredientes_temp"] = valor_limpio
            session_attrs["esperando"] = "tipo"
            
            nombre = session_attrs.get("nombre_temp")
            ingredientes_text = f" con {valor_limpio}" if valor_limpio != "Desconocido" else ""
            
            speak = f"Perfecto, '{nombre}'{ingredientes_text}. ¿De qué tipo de comida es? Si no sabes, di: no sé el tipo."
            return handler_input.response_builder.speak(speak).ask("¿De qué tipo es la receta?").response

        elif esperando == "tipo":
            valor_limpio = RecetarioService.limpiar_y_normalizar_valor(valor, "tipo")
            
            # 4. FINALIZACIÓN y LLAMADA AL SERVICIO
            nombre_final = session_attrs.get("nombre_temp")
            ingredientes_final = session_attrs.get("ingredientes_temp", "Desconocido")
            tipo_final = valor_limpio
            
            nueva_receta = RecetarioService.agregar_receta(handler_input, nombre_final, ingredientes_final, tipo_final)

            # 5. Construcción de la Respuesta Final
            handler_input.attributes_manager.session_attributes = {} # Limpiar sesión
            
            if nueva_receta is False:
                speak_output = f"'{nombre_final}' ya está en tu recetario. {PhrasesManager.get_algo_mas()}"
                reprompt = PhrasesManager.get_preguntas_que_hacer()
            else:
                # Éxito (usamos el objeto Receta normalizado para la respuesta)
                ingredientes_text = f" con {nueva_receta.ingredientes}" if nueva_receta.ingredientes != "Desconocido" else ""
                tipo_text = f", tipo {nueva_receta.tipo}" if nueva_receta.tipo != "Sin categoría" else ""
                
                speak_output = (
                    f"¡{PhrasesManager.get_confirmaciones()}! He agregado '{nueva_receta.nombre}'{ingredientes_text}{tipo_text}. "
                    f"{PhrasesManager.get_algo_mas()}"
                )
                reprompt = PhrasesManager.get_preguntas_que_hacer()

            return handler_input.response_builder.speak(speak_output).ask(reprompt).response
        
        # 6. Fallback (Si 'esperando' no está definido)
        handler_input.attributes_manager.session_attributes = {}
        return (
            handler_input.response_builder
                .speak("Hubo un problema. Empecemos de nuevo. ¿Qué receta quieres agregar?")
                .ask("¿Qué receta quieres agregar?")
                .response
        )


class ListarRecetasIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput):
        return ask_utils.is_intent_name("ListarRecetasIntent")(handler_input)

    def handle(self, handler_input: HandlerInput):
        session_attrs = handler_input.attributes_manager.session_attributes
        
        filtro = ask_utils.get_slot_value(handler_input, "filtro_tipo")
        ingredientes = ask_utils.get_slot_value(handler_input, "ingredientes")
        
        recetas_filtradas, titulo_filtro = RecetarioService.sincronizar_y_filtrar_recetas(
            handler_input, filtro, ingredientes
        )
        
        total_recetas_usuario = len(RecetarioService.get_recetas(handler_input))

        if total_recetas_usuario == 0:
            speak_output = "Aún no tienes recetas en tu recetario. ¿Te gustaría agregar la primera? Solo di: agrega una receta."
            return handler_input.response_builder.speak(speak_output).ask("¿Quieres agregar tu primera receta?").response
            
        if not recetas_filtradas:
            speak_output = f"No encontré recetas{titulo_filtro}. {PhrasesManager.get_algo_mas()}"
            return handler_input.response_builder.speak(speak_output).ask(PhrasesManager.get_preguntas_que_hacer()).response
        
        pagina_actual = 0
        paginacion = RecetarioService.obtener_pagina_recetas(recetas_filtradas, pagina_actual)
        
        recetas_pagina = paginacion["recetas_pagina"]
        total_filtradas = paginacion["total_filtradas"]
        inicio = paginacion["inicio"]
        fin = paginacion["fin"]
        
        if total_filtradas <= RECETAS_POR_PAGINA:
            speak_output = f"Tienes {total_filtradas} recetas{titulo_filtro}: "
            nombres = [f"'{receta.get('nombre', 'Sin nombre')}'" for receta in recetas_pagina]
            speak_output += ", ".join(nombres) + f". {PhrasesManager.get_algo_mas()}"
            
            session_attrs["pagina_recetas"] = 0
            session_attrs["listando_recetas"] = False
            ask_output = PhrasesManager.get_preguntas_que_hacer()
        else:
            speak_output = f"Tienes {total_filtradas} recetas{titulo_filtro}. Te las voy a mostrar de {RECETAS_POR_PAGINA} en {RECETAS_POR_PAGINA}. "
            speak_output += f"Recetas del {inicio + 1} al {fin}: "
            
            nombres = [f"'{receta.get('nombre', 'Sin nombre')}'" for receta in recetas_pagina]
            speak_output += ", ".join(nombres) + ". "
            session_attrs["pagina_recetas"] = pagina_actual + 1
            session_attrs["listando_recetas"] = True
            session_attrs["recetas_filtradas"] = recetas_filtradas
            
            speak_output += f"Quedan {total_filtradas - fin} recetas más. Di 'siguiente' para continuar o 'salir' para terminar."
            ask_output = "¿Quieres ver más recetas? Di 'siguiente' o 'salir'."
            
        return handler_input.response_builder.speak(speak_output).ask(ask_output).response

class PrepararRecetaIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput):
        return ask_utils.is_intent_name("PrepararRecetaIntent")(handler_input)

    def handle(self, handler_input: HandlerInput):
        # 1. Obtener Slots
        nombre = ask_utils.get_slot_value(handler_input, "nombre")
        nombre_persona = ask_utils.get_slot_value(handler_input, "nombre_persona")

        # 2. Flujo: Pedir nombre si falta
        if not nombre:
            prompts = ["¡Claro! ¿Qué receta quieres preparar?", "Por supuesto. ¿Cuál receta vas a preparar?"]
            return handler_input.response_builder.speak(random.choice(prompts)).ask("¿Cuál es el nombre de la receta?").response

        # 3. Lógica de Negocio: Intentar registrar la preparación
        resultado = RecetarioService.registrar_preparacion(handler_input, nombre, nombre_persona)

        # 4. Obtener información de disponibilidad para la respuesta
        num_disponibles, ejemplos_disponibles = RecetarioService.get_recetas_disponibles_info(handler_input)
        
        # 5. Construir Respuesta basada en el resultado
        if resultado == "no_encontrado":
            speak_output = f"Hmm, no encuentro '{nombre}' en tu recetario. "
            if num_disponibles > 0:
                ejemplos = ", ".join(ejemplos_disponibles)
                speak_output += f"Tienes disponibles: {ejemplos}. ¿Cuál quieres preparar?"
            elif RecetarioService.get_recetas(handler_input):
                speak_output += "Todas tus recetas están siendo preparadas o no se reconoce el nombre exacto."
            else:
                speak_output += "De hecho, aún no tienes recetas en tu recetario. Di 'agrega una receta' para empezar."
            return handler_input.response_builder.speak(speak_output).ask("¿Qué receta quieres preparar?").response
            
        elif resultado == "ya_preparando":
            speak_output = f"'{nombre}' ya se está preparando. "
            if num_disponibles > 0:
                ejemplos = ", ".join(ejemplos_disponibles)
                speak_output += f"¿Quieres preparar otra? Tienes disponibles: {ejemplos}."
            else:
                speak_output += "No tienes más recetas disponibles para preparar."
            return handler_input.response_builder.speak(speak_output).ask("¿Qué otra receta quieres preparar?").response

        # Preparación Exitosa (resultado es el objeto Preparacion)
        elif isinstance(resultado, Preparacion):
            preparacion = resultado
            confirmacion = PhrasesManager.get_confirmaciones()
            persona_text = f" por {preparacion.persona}" if preparacion.persona != "un amigo" else "por un amigo"
            
            # Usar la propiedad 'fecha_limite_readable' del objeto Preparacion
            fecha_limite = preparacion.fecha_limite_readable 
                
            speak_output = f"{confirmacion} He registrado la preparación de '{preparacion.nombre}'{persona_text}. "
            speak_output += f"La fecha sugerida para terminarla es el {fecha_limite}. "
            
            if num_disponibles > 0:
                speak_output += f"Te quedan {num_disponibles} recetas disponibles. "
            else:
                speak_output += "¡Ya no te quedan recetas disponibles para preparar! "
                
            speak_output += PhrasesManager.get_algo_mas()

            return handler_input.response_builder.speak(speak_output).ask(PhrasesManager.get_preguntas_que_hacer()).response

        # Fallback de error
        else:
             # Manejo genérico de error que asume el try/except del handler padre
            logger.error(f"Resultado de preparación inesperado: {resultado}")
            raise Exception("Error interno al registrar preparación.")

class LimpiarCacheIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("LimpiarCacheIntent")(handler_input)

    def handle(self, handler_input):
        try:
            user_id = DatabaseManager._user_id(handler_input)
            
            # Limpiar cache en memoria
            global _CACHE
            if user_id in _CACHE:
                del _CACHE[user_id]
            
            # Limpiar sesión
            handler_input.attributes_manager.session_attributes = {}
            
            # Recargar datos desde S3/FakeS3
            user_data = DatabaseManager.get_user_data(handler_input)
            
            # IMPORTANTE: Sincronizar estados
            user_data = sincronizar_estados_recetas(user_data)
            
            # Guardar datos sincronizados
            DatabaseManager.save_user_data(handler_input, user_data)
            
            recetas = user_data.get("recetas_disponibles", [])
            preparaciones = user_data.get("preparaciones_activas", [])
            
            speak_output = "He limpiado el cache y sincronizado tu recetario. "
            speak_output += f"Tienes {len(recetas)} recetas en total y {len(preparaciones)} preparaciones activas. "
            speak_output += phrases.PhrasesManager.get_algo_mas()
            
            return (
                handler_input.response_builder
                    .speak(speak_output)
                    .ask(phrases.PhrasesManager.get_preguntas_que_hacer())
                    .response
            )
        except Exception as e:
            logger.error(f"Error limpiando cache: {e}", exc_info=True)
            return (
                handler_input.response_builder
                    .speak("Hubo un problema limpiando el cache. Intenta de nuevo.")
                    .ask("¿Qué deseas hacer?")
                    .response
            )

# Añadir los demás handlers (los que no cambié)...
class BuscarRecetaIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput):
        return ask_utils.is_intent_name("BuscarRecetaIntent")(handler_input)

    def handle(self, handler_input: HandlerInput):
        try:
            nombre_buscado = ask_utils.get_slot_value(handler_input, "nombre")
            
            if not nombre_buscado:
                return (
                    handler_input.response_builder
                        .speak("¿Qué receta quieres buscar?")
                        .ask("Dime el nombre de la receta que buscas.")
                        .response
                )
            recetas_encontradas = RecetarioService.buscar_recetas(handler_input, nombre_buscado)
            
            speak_output = ""
            if not recetas_encontradas:
                speak_output = f"No encontré ninguna receta con el nombre '{nombre_buscado}'. "
                speak_output += phrases.PhrasesManager.get_algo_mas()
                
            elif len(recetas_encontradas) == 1:
                receta = recetas_encontradas[0]
                speak_output = f"Encontré '{receta['nombre']}'. "
                speak_output += f"Ingredientes: {receta.get('ingredientes', 'Desconocido')}. "
                speak_output += f"Tipo: {receta.get('tipo', 'Sin categoría')}. "
                
                estado = receta.get('estado', 'disponible')
                speak_output += f"Estado: {estado}. "
                
                if receta.get('total_preparaciones', 0) > 0:
                    speak_output += f"Ha sido preparada {receta['total_preparaciones']} veces. "
                
                speak_output += phrases.PhrasesManager.get_algo_mas()
                
            else:
                speak_output = f"Encontré {len(recetas_encontradas)} recetas que coinciden con '{nombre_buscado}': "
                nombres_ingredientes = [
                    f"'{receta['nombre']}' con {receta.get('ingredientes', 'Desconocido')}" 
                    for receta in recetas_encontradas[:3]
                ]
                speak_output += ", ".join(nombres_ingredientes)
                
                if len(recetas_encontradas) > 3:
                    speak_output += f", y {len(recetas_encontradas) - 3} más. "
                else:
                    speak_output += ". "
                    
                speak_output += phrases.PhrasesManager.get_algo_mas()
            return (
                handler_input.response_builder
                    .speak(speak_output)
                    .ask(phrases.PhrasesManager.get_preguntas_que_hacer())
                    .response
            )
            
        except Exception as e:
            logger.error(f"Error en BuscarReceta: {e}", exc_info=True)
            return (
                handler_input.response_builder
                    .speak("Hubo un problema buscando la receta. ¿Intentamos de nuevo?")
                    .ask("¿Qué receta buscas?")
                    .response
            )

class CompletarRecetaIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput):
        return ask_utils.is_intent_name("CompletarRecetaIntent")(handler_input)

    def handle(self, handler_input: HandlerInput):
        try:
            nombre = ask_utils.get_slot_value(handler_input, "nombre")
            id_preparacion = ask_utils.get_slot_value(handler_input, "id_preparacion")
            if not nombre and not id_preparacion:
                prompts = [
                    "¡Qué bien! ¿Qué receta completaste?",
                    "Perfecto, vamos a registrar la receta completada. ¿Cuál receta es?",
                    "¡Excelente! ¿Qué receta estás completando?"
                ]
                return (
                    handler_input.response_builder
                        .speak(random.choice(prompts))
                        .ask("¿Cuál es el nombre de la receta?")
                        .response
                )
            resultado = RecetarioService.registrar_completacion(handler_input, nombre, id_preparacion)
            num_preparando, ejemplos_preparando = RecetarioService.get_preparaciones_activas_info(handler_input)

            speak_output = ""
            
            if resultado == "no_preparaciones":
                speak_output = "No tienes recetas en preparación en este momento. Todas tus recetas están disponibles. "
                speak_output += phrases.PhrasesManager.get_algo_mas()
            
            elif resultado == "no_encontrado":
                speak_output = f"Hmm, no encontré una preparación activa para '{nombre or id_preparacion}'. "
                
                if num_preparando == 1:
                    speak_output += f"Solo tienes en preparación {ejemplos_preparando[0]}. ¿Es esa?"
                elif num_preparando > 1:
                    speak_output += f"Tienes en preparación: {', '.join(ejemplos_preparando)}. ¿Cuál de estas es?"
                else:
                    speak_output += "De hecho, ¡ya no tienes recetas en preparación!"
                
                return handler_input.response_builder.speak(speak_output).ask("¿Cuál receta quieres completar?").response
            
            elif isinstance(resultado, dict):
                preparacion_finalizada = resultado
                confirmacion = phrases.PhrasesManager.get_confirmaciones()
                
                speak_output = f"{confirmacion} He registrado la completación de '{preparacion_finalizada['nombre']}'. "
                
                if preparacion_finalizada.get("completada_a_tiempo", True):
                    speak_output += "¡Fue completada a tiempo! "
                else:
                    speak_output += "Fue completada un poco tarde, pero no hay problema. "
                
                speak_output += "Espero que la hayan disfrutado. "
                
                if num_preparando > 0:
                    speak_output += f"Aún tienes {num_preparando} "
                    speak_output += "receta en preparación. " if num_preparando == 1 else "recetas en preparación. "
                
                speak_output += phrases.PhrasesManager.get_algo_mas()
            else:
                raise Exception("Resultado de completación inesperado.")
            return (
                handler_input.response_builder
                    .speak(speak_output)
                    .ask(phrases.PhrasesManager.get_preguntas_que_hacer())
                    .response
            )
            
        except Exception as e:
            logger.error(f"Error en CompletarReceta: {e}", exc_info=True)
            return (
                handler_input.response_builder
                    .speak("Tuve un problema registrando la completación. ¿Lo intentamos de nuevo?")
                    .ask("¿Qué receta quieres completar?")
                    .response
            )

class ConsultarPreparacionesIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput):
        return ask_utils.is_intent_name("ConsultarPreparacionesIntent")(handler_input)

    def handle(self, handler_input: HandlerInput):
        try:
            resumen = RecetarioService.obtener_resumen_preparaciones(handler_input)
            
            total_preparaciones = resumen["total"]
            
            if total_preparaciones == 0:
                speak_output = "¡Excelente! No tienes ninguna receta en preparación en este momento. Todas están disponibles. "
                speak_output += phrases.PhrasesManager.get_algo_mas()
            else:
                detalles = resumen["detalles"]
                
                if total_preparaciones == 1:
                    speak_output = "Déjame ver... Solo tienes una receta en preparación: "
                else:
                    speak_output = f"Déjame revisar... Tienes {total_preparaciones} recetas en preparación. Estas son las primeras: "
                
                speak_output += "; ".join(detalles[:5]) + ". "
                
                if total_preparaciones > 5:
                    speak_output += f"Y {total_preparaciones - 5} más. "
                
                if resumen["hay_vencidas"]:
                    speak_output += "¡ALERTA! Tienes recetas vencidas. Te sugiero completarlas pronto. "
                elif resumen["hay_proximas"]:
                    speak_output += "Algunas están por vencer, ¡no lo olvides! "
                
                speak_output += phrases.PhrasesManager.get_algo_mas()
            
            return (
                handler_input.response_builder
                    .speak(speak_output)
                    .ask(phrases.PhrasesManager.get_preguntas_que_hacer())
                    .response
            )
            
        except Exception as e:
            logger.error(f"Error en ConsultarPreparaciones: {e}", exc_info=True)
            return (
                handler_input.response_builder
                    .speak("Hubo un problema consultando las preparaciones. ¿Intentamos de nuevo?")
                    .ask("¿Qué más deseas hacer?")
                    .response
            )

class ConsultarCompletadasIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput):
        return ask_utils.is_intent_name("ConsultarCompletadasIntent")(handler_input)

    def handle(self, handler_input: HandlerInput):
        try:
            resumen = RecetarioService.obtener_resumen_historial(handler_input)
            
            total = resumen["total"]
            
            if total == 0:
                speak_output = "Aún no has registrado recetas completadas. Cuando prepares recetas y las completes, aparecerán aquí. "
            else:
                speak_output = f"Has registrado {total} "
                speak_output += "completación en total. " if total == 1 else "completaciones en total. "
                
                detalles = resumen["detalles_voz"]
                
                if resumen["es_historial_completo"]:
                    speak_output += "Las recetas completadas son: "
                    speak_output += ", ".join(detalles) + ". "
                else:
                    speak_output += "Las 5 más recientes son: "
                    speak_output += ", ".join(detalles) + ". "
                    speak_output += f"Tienes {total - 5} completaciones más en tu historial. "
            
            speak_output += phrases.PhrasesManager.get_algo_mas()
            return (
                handler_input.response_builder
                    .speak(speak_output)
                    .ask(phrases.PhrasesManager.get_preguntas_que_hacer())
                    .response
            )
            
        except Exception as e:
            logger.error(f"Error en ConsultarCompletadas: {e}", exc_info=True)
            return (
                handler_input.response_builder
                    .speak("Hubo un problema consultando el historial.")
                    .ask("¿Qué más deseas hacer?")
                    .response
            )

class EliminarRecetaIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput):
        return ask_utils.is_intent_name("EliminarRecetaIntent")(handler_input)

    def handle(self, handler_input: HandlerInput):
        try:
            nombre = ask_utils.get_slot_value(handler_input, "nombre")
            if not nombre:
                prompts = [
                    "¿Qué receta quieres eliminar de tu recetario?",
                    "Dime el nombre de la receta que ya no quieres conservar.",
                ]
                return (
                    handler_input.response_builder
                        .speak(random.choice(prompts))
                        .ask("¿Cuál es el nombre?")
                        .response
                )
            resultado = RecetarioService.eliminar_receta(handler_input, nombre)
            speak_output = ""
            
            if resultado == "no_encontrado":
                speak_output = f"No encontré la receta '{nombre}' en tu recetario. Asegúrate de que el nombre sea exacto. "
                speak_output += phrases.PhrasesManager.get_algo_mas()
            
            elif resultado == "esta_preparando":
                speak_output = f"No puedo eliminar '{nombre}' porque actualmente se está preparando. Primero completa la preparación. "
                speak_output += "Di 'completar receta' cuando la termines. "
            
            elif isinstance(resultado, dict):
                receta_eliminada = resultado
                confirmacion = phrases.PhrasesManager.get_confirmaciones()
                
                speak_output = f"{confirmacion} He eliminado '{receta_eliminada['nombre']}' de tu recetario. "
                total_recetas = RecetarioService.get_recetas(handler_input)
                speak_output += f"Ahora tienes {len(total_recetas)} recetas. "
                speak_output += phrases.PhrasesManager.get_algo_mas()
            
            else:
                speak_output = "Hubo un problema al intentar eliminar la receta. ¿Intentamos de nuevo?"
            return (
                handler_input.response_builder
                    .speak(speak_output)
                    .ask(phrases.PhrasesManager.get_preguntas_que_hacer())
                    .response
            )
            
        except Exception as e:
            logger.error(f"Error en EliminarReceta: {e}", exc_info=True)
            return (
                handler_input.response_builder
                    .speak("Hubo un problema procesando tu solicitud de eliminación. ¿Qué más deseas hacer?")
                    .ask("¿Qué más deseas hacer?")
                    .response
            )

class MostrarOpcionesIntentHandler(AbstractRequestHandler):
    """Handler para cuando el usuario pide que le repitan las opciones"""
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("MostrarOpcionesIntent")(handler_input)

    def handle(self, handler_input):
        try:
            user_data = DatabaseManager.get_user_data(handler_input)
            total_recetas = len(user_data.get("recetas_disponibles", []))
            
            intro = "¡Por supuesto! "
            opciones = phrases.PhrasesManager.get_opciones_menu()
            
            # Agregar contexto si es útil
            if total_recetas == 0:
                contexto = " Como aún no tienes recetas, te sugiero empezar agregando algunas."
            elif len(user_data.get("preparaciones_activas", [])) > 0:
                contexto = " Recuerda que tienes algunas recetas en preparación."
            else:
                contexto = ""
            
            pregunta = " " + phrases.PhrasesManager.get_preguntas_que_hacer()
            
            speak_output = intro + opciones + contexto + pregunta
            
            return (
                handler_input.response_builder
                    .speak(speak_output)
                    .ask(phrases.PhrasesManager.get_preguntas_que_hacer())
                    .response
            )
        except Exception as e:
            logger.error(f"Error mostrando opciones: {e}", exc_info=True)
            return (
                handler_input.response_builder
                    .speak("Puedo ayudarte a gestionar tu recetario. ¿Qué te gustaría hacer?")
                    .ask("¿En qué puedo ayudarte?")
                    .response
            )

class SiguientePaginaIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        # Solo manejar si estamos en contexto de paginación
        session_attrs = handler_input.attributes_manager.session_attributes
        is_listing = session_attrs.get("listando_recetas", False)
        
        return (ask_utils.is_intent_name("SiguientePaginaIntent")(handler_input) and is_listing)

    def handle(self, handler_input):
        try:
            session_attrs = handler_input.attributes_manager.session_attributes
            
            # Verificación adicional de seguridad
            if not session_attrs.get("listando_recetas"):
                # Si alguien llegó aquí sin estar listando, redirigir amablemente
                return (
                    handler_input.response_builder
                        .speak("¿Qué te gustaría hacer? Puedo ayudarte a listar recetas, agregar una nueva, o preparar una receta.")
                        .ask("¿En qué puedo ayudarte?")
                        .response
                )
            
            # Continuar con la paginación
            handler = ListarRecetasIntentHandler()
            return handler.handle(handler_input)
            
        except Exception as e:
            logger.error(f"Error en SiguientePagina: {e}", exc_info=True)
            return (
                handler_input.response_builder
                    .speak("Hubo un problema. ¿Qué te gustaría hacer?")
                    .ask("¿En qué puedo ayudarte?")
                    .response
            )

class SalirListadoIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("SalirListadoIntent")(handler_input)

    def handle(self, handler_input):
        # Limpiar estado de paginación
        session_attrs = handler_input.attributes_manager.session_attributes
        session_attrs["pagina_recetas"] = 0
        session_attrs["listando_recetas"] = False
        
        speak_output = "De acuerdo, terminé de mostrar las recetas. " + phrases.PhrasesManager.get_algo_mas()
        
        return (
            handler_input.response_builder
                .speak(speak_output)
                .ask(phrases.PhrasesManager.get_preguntas_que_hacer())
                .response
        )

# ==============================
# Handlers estándar
# ==============================
class HelpIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):
        speak_output = (
            "¡Por supuesto! Te explico cómo funciona tu recetario. "
            "Puedes agregar recetas nuevas diciendo 'agrega una receta', "
            "ver todas tus recetas con 'lista mis recetas', "
            "buscar una receta específica con 'busca' y el nombre, "
            "preparar una receta diciendo 'prepara' seguido del nombre, "
            "registrar recetas completadas con 'completo' y el nombre, "
            "o consultar tus preparaciones activas preguntando 'qué recetas tengo en preparación'. "
            "¿Qué te gustaría hacer primero?"
        )
        return (
            handler_input.response_builder
                .speak(speak_output)
                .ask("¿Con qué te ayudo?")
                .response
        )

class CancelOrStopIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return (ask_utils.is_intent_name("AMAZON.CancelIntent")(handler_input) or
                ask_utils.is_intent_name("AMAZON.StopIntent")(handler_input))

    def handle(self, handler_input):
        # Limpiar sesión al salir
        handler_input.attributes_manager.session_attributes = {}
        
        despedidas = [
            "¡Hasta luego! Que disfrutes tu cocina.",
            "¡Nos vemos pronto! Espero que disfrutes tus recetas.",
            "¡Adiós! Fue un gusto ayudarte con tu recetario.",
            "¡Hasta la próxima! Feliz cocina.",
            "¡Que tengas un excelente día! Disfruta tus recetas."
        ]
        
        return (
            handler_input.response_builder
                .speak(random.choice(despedidas))
                .response
        )

class SessionEndedRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input):
        # Limpiar sesión
        handler_input.attributes_manager.session_attributes = {}
        return handler_input.response_builder.response

class FallbackIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("AMAZON.FallbackIntent")(handler_input)

    def handle(self, handler_input):
        session_attrs = handler_input.attributes_manager.session_attributes
        
        # Si estamos agregando una receta, manejar las respuestas
        if session_attrs.get("agregando_receta"):
            paso_actual = session_attrs.get("esperando")  # Usar "esperando" en lugar de "paso_actual"
            
            # Para el fallback, Alexa a veces incluye el texto en el intent name o en slots genéricos
            # Vamos a asumir que el usuario respondió correctamente
            
            if paso_actual == "nombre":
                # El usuario probablemente dijo el nombre pero Alexa no lo reconoció
                return (
                    handler_input.response_builder
                        .speak("No entendí bien el nombre. ¿Puedes repetirlo más despacio?")
                        .ask("¿Cuál es el nombre de la receta?")
                        .response
                )
            
            elif paso_actual == "ingredientes":
                # Asumimos que dijo "no sé" o unos ingredientes no reconocidos
                session_attrs["ingredientes_temp"] = "Desconocido"
                session_attrs["esperando"] = "tipo"
                nombre = session_attrs.get("nombre_temp")
                
                return (
                    handler_input.response_builder
                        .speak(f"De acuerdo, continuemos con '{nombre}'. ¿De qué tipo de comida es? Por ejemplo: mexicana, italiana, postre. Si no sabes, di: no sé.")
                        .ask("¿De qué tipo es la receta?")
                        .response
                )
            
            elif paso_actual == "tipo":
                # Asumimos que dijo "no sé" o un tipo no reconocido
                nombre_final = session_attrs.get("nombre_temp")
                ingredientes_final = session_attrs.get("ingredientes_temp", "Desconocido")
                tipo_final = "Sin categoría"
                
                # Usar el servicio para agregar la receta
                nueva_receta = RecetarioService.agregar_receta(handler_input, nombre_final, ingredientes_final, tipo_final)
                
                # Limpiar sesión
                handler_input.attributes_manager.session_attributes = {}
                
                if nueva_receta is False:
                    speak_output = f"'{nombre_final}' ya está en tu recetario. {PhrasesManager.get_algo_mas()}"
                else:
                    ingredientes_text = f" con {nueva_receta.ingredientes}" if nueva_receta.ingredientes != "Desconocido" else ""
                    speak_output = f"¡Perfecto! He agregado '{nueva_receta.nombre}'{ingredientes_text}. "
                    speak_output += f"Ahora tienes {len(RecetarioService.get_recetas(handler_input))} recetas en tu recetario. "
                    speak_output += PhrasesManager.get_algo_mas()
                
                return (
                    handler_input.response_builder
                        .speak(speak_output)
                        .ask(PhrasesManager.get_preguntas_que_hacer())
                        .response
                )
        
        # Si estamos listando recetas con paginación
        if session_attrs.get("listando_recetas"):
            speak_output = "No entendí eso. ¿Quieres ver más recetas? Di 'siguiente' para continuar o 'salir' para terminar."
            ask_output = "Di 'siguiente' o 'salir'."
        else:
            # Comportamiento normal del fallback
            respuestas = [
                "Disculpa, no entendí eso. ¿Podrías repetirlo de otra forma?",
                "Hmm, no estoy seguro de qué quisiste decir. ¿Me lo puedes decir de otra manera?",
                "Perdón, no comprendí. ¿Puedes intentarlo de nuevo?"
            ]
            
            speak_output = random.choice(respuestas)
            speak_output += " Recuerda que puedo ayudarte a agregar recetas, listarlas, prepararlas o registrar completaciones."
            ask_output = "¿Qué te gustaría hacer?"
        
        return (
            handler_input.response_builder
                .speak(speak_output)
                .ask(ask_output)
                .response
        )

class CatchAllExceptionHandler(AbstractExceptionHandler):
    def can_handle(self, handler_input, exception):
        return True

    def handle(self, handler_input, exception):
        logger.error(f"Exception: {exception}", exc_info=True)
        # Limpiar sesión en caso de error
        handler_input.attributes_manager.session_attributes = {}
        
        respuestas = [
            "Ups, algo no salió como esperaba. ¿Podemos intentarlo de nuevo?",
            "Perdón, tuve un pequeño problema. ¿Lo intentamos otra vez?",
            "Disculpa, hubo un inconveniente. ¿Qué querías hacer?"
        ]
        
        return (
            handler_input.response_builder
                .speak(random.choice(respuestas))
                .ask("¿En qué puedo ayudarte?")
                .response
        )

# ==============================
# Registrar handlers - ORDEN CRÍTICO
# ==============================
sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(MostrarOpcionesIntentHandler())

# ContinuarAgregarHandler DEBE ir ANTES que otros handlers para interceptar respuestas
sb.add_request_handler(ContinuarAgregarHandler())

# Handlers que usan patrones de diseño
sb.add_request_handler(RecetaBuilderHandler())
sb.add_request_handler(PreparacionBuilderHandler())

# Luego AgregarRecetaIntentHandler
sb.add_request_handler(AgregarRecetaIntentHandler())

# Luego los demás handlers
sb.add_request_handler(ListarRecetasIntentHandler())
sb.add_request_handler(BuscarRecetaIntentHandler())
sb.add_request_handler(PrepararRecetaIntentHandler())
sb.add_request_handler(CompletarRecetaIntentHandler())
sb.add_request_handler(ConsultarPreparacionesIntentHandler())
sb.add_request_handler(ConsultarCompletadasIntentHandler())
sb.add_request_handler(EliminarRecetaIntentHandler())
sb.add_request_handler(LimpiarCacheIntentHandler())
sb.add_request_handler(SiguientePaginaIntentHandler())
sb.add_request_handler(SalirListadoIntentHandler())
sb.add_request_handler(HelpIntentHandler())
sb.add_request_handler(CancelOrStopIntentHandler())
sb.add_request_handler(FallbackIntentHandler())
sb.add_request_handler(SessionEndedRequestHandler())
sb.add_exception_handler(CatchAllExceptionHandler())

# ==============================
# Demostración de patrones aplicados
# ==============================
def demonstrar_patrones_lambda():
    """
    Función de demostración de los patrones aplicados en lambda_function.py
    Esta función muestra cómo se usan los patrones sin necesidad de handler_input real
    """
    print("=== PATRONES DE DISEÑO EN LAMBDA_FUNCTION.PY ===")
    
    # 1. Factory Pattern
    print("\n1. FACTORY PATTERN:")
    print("   - HandlerFactory.get_response_strategy('welcome')")
    print("   - HandlerFactory.create_builder_based_handler('receta')")
    
    # 2. Strategy Pattern  
    print("\n2. STRATEGY PATTERN:")
    welcome_strategy = HandlerFactory.get_response_strategy('welcome')
    error_strategy = HandlerFactory.get_response_strategy('error')
    print(f"   - Estrategia Welcome: {type(welcome_strategy).__name__}")
    print(f"   - Estrategia Error: {type(error_strategy).__name__}")
    
    # 3. Template Method Pattern
    print("\n3. TEMPLATE METHOD PATTERN:")
    print("   - BaseSkillHandler define el flujo común:")
    print("     * prepare_context() -> validate_input() -> process_business_logic() -> generate_response()")
    print("   - Los handlers específicos implementan los métodos abstractos")
    
    # 4. Builder Pattern en Handlers
    print("\n4. BUILDER PATTERN EN HANDLERS:")
    print("   - RecetaBuilderHandler usa RecetaBuilder para crear recetas")
    print("   - PreparacionBuilderHandler usa PreparacionBuilder")
    
    # 5. Singleton Pattern (desde database.py)
    print("\n5. SINGLETON PATTERN:")
    print("   - DatabaseManager mantiene una instancia única")
    
    print("\n=== BENEFICIOS OBTENIDOS ===")
    print("✅ Código más organizado y mantenible")
    print("✅ Fácil extensión con nuevos handlers")
    print("✅ Separación clara de responsabilidades")
    print("✅ Reutilización de componentes")
    print("✅ Testing más sencillo")

# Crear el handler principal
lambda_handler = sb.lambda_handler()

# Comentar la siguiente línea para desactivar la demostración
# demonstrar_patrones_lambda()