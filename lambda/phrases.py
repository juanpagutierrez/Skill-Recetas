import random

class PhrasesManager:
    # ==============================
    SALUDOS = [
        "¡Hola! ¡Qué gusto tenerte aquí en la cocina!",
        "¡Bienvenido de vuelta a tu recetario!",
        "¡Hola! Me alegra que estés cocinando hoy.",
        "¡Qué bueno verte por aquí! ¿Listo para cocinar?",
        "¡Hola! Espero que tengas un excelente día de cocina."
    ]
    
    OPCIONES_MENU = [
        "Puedo ayudarte a gestionar tu recetario personal. Puedes agregar recetas nuevas, ver tu lista de recetas, preparar recetas, registrar recetas completadas o consultar qué recetas tienes en preparación.",
        "Tengo varias opciones para ti: agregar recetas a tu colección, listar todas tus recetas, preparar una receta, marcar una receta como completada, o ver tus preparaciones activas.",
        "Puedo hacer varias cosas: agregar recetas nuevas a tu recetario, mostrarte qué recetas tienes, ayudarte a preparar recetas, registrar cuando las completas, o decirte qué recetas están en preparación."
    ]
    
    PREGUNTAS_QUE_HACER = [
        "¿Qué te gustaría hacer hoy en la cocina?",
        "¿En qué puedo ayudarte con tus recetas?",
        "¿Qué necesitas preparar?",
        "¿Cómo puedo ayudarte con tu recetario?",
        "¿Qué quieres cocinar hoy?"
    ]
    
    ALGO_MAS = [
        "¿Hay algo más en lo que pueda ayudarte en la cocina?",
        "¿Necesitas algo más para preparar?",
        "¿Qué más puedo hacer por ti?",
        "¿Te ayudo con alguna otra receta?",
        "¿Hay algo más que quieras cocinar?"
    ]
    
    CONFIRMACIONES = [
        "¡Perfecto!",
        "¡Excelente!",
        "¡Genial!",
        "¡Muy bien!",
        "¡Estupendo!"
    ]
    
    @staticmethod
    def get_random_phrase(phrase_list):
        """Selecciona una frase aleatoria de una lista"""
        return random.choice(phrase_list)
    
    @classmethod
    def get_saludo(cls): 
        saludo = cls.get_random_phrase(cls.SALUDOS) 
        return saludo
        
    @classmethod
    def get_opciones_menu(cls):
        opcion = cls.get_random_phrase(cls.OPCIONES_MENU)
        return opcion
        
    @classmethod
    def get_preguntas_que_hacer(cls):
        pregunta_que_hacer = cls.get_random_phrase(cls.PREGUNTAS_QUE_HACER)
        return pregunta_que_hacer
    
    @classmethod
    def get_algo_mas(cls):
        algo_mas = cls.get_random_phrase(cls.ALGO_MAS)
        return algo_mas
    
    @classmethod
    def get_confirmaciones(cls):
        confirmacion = cls.get_random_phrase(cls.CONFIRMACIONES)
        return confirmacion

    @classmethod
    def get_welcome_message(cls, user_data, total_recetas, preparaciones_activas, usuario_frecuente):
        if usuario_frecuente and total_recetas > 0:
            saludo = "¡Hola de nuevo! ¡Qué bueno verte por aquí en la cocina!"
            estado = f"Veo que tienes {total_recetas} recetas en tu recetario"
            if preparaciones_activas > 0:
                estado += f" y {preparaciones_activas} preparaciones activas."
            else:
                estado += "."
        else:
            saludo = cls.get_saludo() 
            if total_recetas == 0:
                estado = "Veo que es tu primera vez aquí. ¡Empecemos a construir tu recetario!"
            else:
                estado = f"Tienes {total_recetas} recetas en tu colección. ¿Qué quieres preparar?"
                
        opciones = cls.get_opciones_menu()
        pregunta = cls.get_preguntas_que_hacer()   
                
        return f"{saludo} {estado} {opciones} {pregunta}"