import logging
from config import ENABLE_DDB_CACHE, CACHE_TTL_SECONDS
import boto3
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from repositories import IPersistenceAdapter, ICacheStrategy, IUserRepository

logger = logging.getLogger(__name__)

# ==============================
# Implementaciones de Adaptadores de Persistencia
# ==============================
_FAKE_STORE = {}

class FakeS3Adapter(IPersistenceAdapter):
    """Implementación en memoria del adaptador de persistencia - Single Responsibility"""
    
    def __init__(self):
        logger.info("🧪 Usando FakeS3Adapter (memoria)")

    @staticmethod
    def _user_id_from_envelope(request_envelope):
        return request_envelope.context.system.user.user_id

    def get_attributes(self, request_envelope):
        uid = self._user_id_from_envelope(request_envelope)
        return _FAKE_STORE.get(uid, {})

    def save_attributes(self, request_envelope, attributes):
        uid = self._user_id_from_envelope(request_envelope)
        _FAKE_STORE[uid] = attributes or {}
        logger.info(f"FakeS3Adapter: guardados atributos para {uid}")

    def delete_attributes(self, request_envelope):
        uid = self._user_id_from_envelope(request_envelope)
        if uid in _FAKE_STORE:
            del _FAKE_STORE[uid]
            logger.info(f"FakeS3Adapter: atributos borrados para {uid}")


# ==============================
# Implementaciones de Estrategias de Cache
# ==============================
class InMemoryCacheStrategy(ICacheStrategy):
    """Cache en memoria con TTL - Single Responsibility"""
    
    def __init__(self, ttl_seconds: int = CACHE_TTL_SECONDS):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._ttl_seconds = ttl_seconds
    
    def get(self, user_id: str) -> Optional[Dict[str, Any]]:
        item = self._cache.get(user_id)
        if not item:
            return None
        if datetime.now().timestamp() > item["expire_at"]:
            self._cache.pop(user_id, None)
            return None
        return item["data"]
    
    def put(self, user_id: str, data: Dict[str, Any]) -> None:
        self._cache[user_id] = {
            "data": data,
            "expire_at": (datetime.now() + timedelta(seconds=self._ttl_seconds)).timestamp()
        }
    
    def invalidate(self, user_id: str) -> None:
        self._cache.pop(user_id, None)


class DynamoDBCacheStrategy(ICacheStrategy):
    """Cache en DynamoDB con TTL - Single Responsibility"""
    
    def __init__(self, table_name: str = "RecetarioSkillCache"):
        self._table_name = table_name
        self._dynamodb = boto3.resource("dynamodb", region_name="us-east-1") if ENABLE_DDB_CACHE else None
    
    def _get_table(self):
        if not ENABLE_DDB_CACHE or not self._dynamodb:
            return None
        try:
            table = self._dynamodb.Table(self._table_name)
            table.load()
            return table
        except Exception as e:
            logger.warning(f"DDB deshabilitado o sin permisos: {e}")
            return None
    
    def get(self, user_id: str) -> Optional[Dict[str, Any]]:
        try:
            table = self._get_table()
            if not table:
                return None
            resp = table.get_item(Key={"user_id": user_id})
            if "Item" in resp:
                return resp["Item"].get("data", {})
        except Exception as e:
            logger.warning(f"DDB get_item error: {e}")
        return None
    
    def put(self, user_id: str, data: Dict[str, Any]) -> None:
        try:
            table = self._get_table()
            if not table:
                return
            table.put_item(Item={
                "user_id": user_id,
                "data": data,
                "ttl": int((datetime.now() + timedelta(seconds=CACHE_TTL_SECONDS)).timestamp())
            })
        except Exception as e:
            logger.warning(f"DDB put_item error: {e}")
    
    def invalidate(self, user_id: str) -> None:
        try:
            table = self._get_table()
            if table:
                table.delete_item(Key={"user_id": user_id})
        except Exception as e:
            logger.warning(f"DDB delete_item error: {e}")


# ==============================
# Repositorio de Usuario - Implementa IUserRepository
# ==============================
class UserRepository(IUserRepository):
    """Repositorio de usuarios con cache multi-nivel - Single Responsibility"""
    
    def __init__(self, 
                 persistence_adapter: IPersistenceAdapter,
                 memory_cache: ICacheStrategy,
                 ddb_cache: Optional[ICacheStrategy] = None):
        self._persistence = persistence_adapter
        self._memory_cache = memory_cache
        self._ddb_cache = ddb_cache
    
    def _user_id(self, handler_input):
        return handler_input.request_envelope.context.system.user.user_id

    def get_user_data(self, handler_input) -> Dict[str, Any]:
        user_id = self._user_id(handler_input)

        # 1) Cache en memoria
        data = self._memory_cache.get(user_id)
        if data is not None:
            logger.info("⚡ Cache hit (memoria)")
            return data

        # 2) Cache en DDB (opcional)
        if self._ddb_cache:
            data = self._ddb_cache.get(user_id)
            if data is not None:
                logger.info("⚡ Cache hit (DynamoDB)")
                self._memory_cache.put(user_id, data)
                return data

        # 3) Persistencia principal
        attr_mgr = handler_input.attributes_manager
        persistent = attr_mgr.persistent_attributes
        if not persistent:
            persistent = self.get_initial_data()
            attr_mgr.persistent_attributes = persistent
            attr_mgr.save_persistent_attributes()

        # 4) Actualizar cachés
        self._memory_cache.put(user_id, persistent)
        if self._ddb_cache:
            self._ddb_cache.put(user_id, persistent)

        return persistent

    def save_user_data(self, handler_input, data: Dict[str, Any]) -> None:
        user_id = self._user_id(handler_input)

        # Persistencia principal
        attr_mgr = handler_input.attributes_manager
        attr_mgr.persistent_attributes = data
        attr_mgr.save_persistent_attributes()

        # Actualizar cachés
        self._memory_cache.put(user_id, data)
        if self._ddb_cache:
            self._ddb_cache.put(user_id, data)

    def get_initial_data(self) -> Dict[str, Any]:
        return {
            "recetas_disponibles": [],
            "preparaciones_activas": [],
            "historial_preparaciones": [],
            "estadisticas": {
                "total_recetas": 0,
                "total_preparaciones": 0,
                "total_completaciones": 0
            },
            "historial_conversaciones": [],
            "configuracion": {"limite_preparaciones": 10, "dias_preparacion": 7},
            "usuario_frecuente": False
        }


# ==============================
# DatabaseManager - Facade Pattern para compatibilidad con código existente
# ==============================
class DatabaseManager:
    """Facade que delega al repositorio - facilita migración gradual"""
    
    _repository: Optional[IUserRepository] = None
    
    @classmethod
    def initialize(cls, repository: IUserRepository):
        """Inicializa el repositorio a usar"""
        cls._repository = repository
    
    @classmethod
    def _user_id(cls, handler_input):
        return handler_input.request_envelope.context.system.user.user_id
    
    @classmethod
    def get_user_data(cls, handler_input) -> Dict[str, Any]:
        if cls._repository is None:
            raise RuntimeError("DatabaseManager no inicializado. Llama a DatabaseManager.initialize() primero")
        return cls._repository.get_user_data(handler_input)
    
    @classmethod
    def save_user_data(cls, handler_input, data: Dict[str, Any]) -> None:
        if cls._repository is None:
            raise RuntimeError("DatabaseManager no inicializado. Llama a DatabaseManager.initialize() primero")
        cls._repository.save_user_data(handler_input, data)
    
    @classmethod
    def initial_data(cls) -> Dict[str, Any]:
        if cls._repository is None:
            raise RuntimeError("DatabaseManager no inicializado. Llama a DatabaseManager.initialize() primero")
        return cls._repository.get_initial_data()
