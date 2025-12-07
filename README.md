# Skill Recetas - Alexa Skill

Sistema de gestión de recetas de cocina por voz para Amazon Alexa.

## Características Principales

- **Agregar recetas**: Guarda recetas con nombre, ingredientes y tipo
- **Listar recetas**: Visualiza tu colección completa con paginación
- **Buscar recetas**: Encuentra recetas por nombre
- **Preparar recetas**: Registra qué recetas estás cocinando
- **Completar recetas**: Marca recetas como terminadas
- **Consultar estado**: Ve qué tienes en preparación y completado

## Patrones de Diseño Implementados

Este proyecto implementa varios patrones de diseño de software que mejoran la arquitectura y mantenibilidad:

### Singleton Pattern
- **Ubicación**: `database.py` - `DatabaseManager`
- **Propósito**: Garantiza una única instancia del gestor de base de datos

### Builder Pattern
- **Ubicación**: `models.py` - `RecetaBuilder`, `PreparacionBuilder`
- **Propósito**: Construcción fluida y flexible de objetos complejos

### Prototype Pattern
- **Ubicación**: `models.py` - `Receta.clone()`, `Preparacion.clone()`
- **Propósito**: Clonado eficiente de objetos existentes

### Facade Pattern
- **Ubicación**: `services.py` - `RecetarioService`
- **Propósito**: Interfaz simplificada para operaciones complejas

### Factory Pattern
- **Ubicación**: `lambda_function.py` - `HandlerFactory`
- **Propósito**: Creación centralizada de handlers y estrategias

### Strategy Pattern
- **Ubicación**: `lambda_function.py` - `ResponseStrategy`
- **Propósito**: Diferentes estrategias de respuesta según el contexto

### Template Method Pattern
- **Ubicación**: `lambda_function.py` - `BaseSkillHandler`
- **Propósito**: Define flujo común para todos los handlers

## Estructura del Proyecto

```
├── lambda_function.py      # Handlers principales de Alexa
├── models.py              # Modelos con Builder y Prototype patterns
├── database.py            # DatabaseManager con Singleton pattern
├── services.py            # Facade pattern para servicios
├── examples_patterns.py   # Ejemplos de uso de patrones
├── phrases.py             # Frases y respuestas
├── config.py              # Configuración
└── skill.json            # Configuración de la skill
```

## Beneficios de los Patrones Implementados

1. **Mantenibilidad**: Código más organizado y fácil de modificar
2. **Reusabilidad**: Componentes que se pueden reutilizar fácilmente  
3. **Testabilidad**: Facilita las pruebas unitarias
4. **Flexibilidad**: Permite extensiones futuras sin romper código existente
5. **Legibilidad**: Código más expresivo y comprensible

## Frases de Invocación

- **Abrir skill**: "Alexa, abre Recetario"
- **Agregar**: "agrega una receta"
- **Listar**: "lista mis recetas"  
- **Buscar**: "busca [nombre de receta]"
- **Preparar**: "preparar [nombre de receta]"
- **Completar**: "completar [nombre de receta]"



## Autores

- Barraza C. Diego A.
- Gutierrez G. Juan P.