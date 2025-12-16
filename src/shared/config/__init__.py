"""
Configuration Management
========================

Centralized configuration management using Pydantic Settings.
All configuration is loaded from environment variables with sensible defaults.
"""

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Database connection settings."""

    model_config = SettingsConfigDict(env_prefix="DB_")

    host: str = "localhost"
    port: int = 5432
    name: str = "truth_engine"
    user: str = "truth_engine"
    password: str = "truth_engine_dev"
    pool_size: int = 10
    max_overflow: int = 20
    echo: bool = False

    @property
    def url(self) -> str:
        """Construct the database URL."""
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"

    @property
    def sync_url(self) -> str:
        """Construct a synchronous database URL."""
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class ObjectStoreSettings(BaseSettings):
    """Object storage settings (S3-compatible)."""

    model_config = SettingsConfigDict(env_prefix="S3_")

    endpoint_url: str = "http://localhost:9000"
    access_key: str = "minio_dev"
    secret_key: str = "minio_dev_secret"
    bucket_name: str = "truth-engine"
    region: str = "us-east-1"
    use_ssl: bool = False


class GraphStoreSettings(BaseSettings):
    """Graph database settings."""

    model_config = SettingsConfigDict(env_prefix="GRAPH_")

    # EXTENSION_POINT: A2+ will implement concrete graph store connection
    enabled: bool = False
    host: str = "localhost"
    port: int = 7687
    user: str = "neo4j"
    password: str = "neo4j_dev"


class VectorStoreSettings(BaseSettings):
    """Vector store settings."""

    model_config = SettingsConfigDict(env_prefix="VECTOR_")

    # EXTENSION_POINT: A3+ will implement concrete vector store connection
    enabled: bool = False
    host: str = "localhost"
    port: int = 6333
    collection_name: str = "truth_engine"


class ServiceSettings(BaseSettings):
    """Common service settings."""

    model_config = SettingsConfigDict(env_prefix="SERVICE_")

    name: str = "truth-engine"
    version: str = "0.1.0"
    environment: str = "development"
    debug: bool = True
    log_level: str = "INFO"


class Settings(BaseSettings):
    """
    Root configuration container.
    
    All settings are loaded from environment variables.
    Nested settings use prefixes (e.g., DB_HOST, S3_BUCKET_NAME).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Service identification
    service_name: str = Field(default="truth-engine", alias="SERVICE_NAME")
    service_version: str = Field(default="0.1.0", alias="SERVICE_VERSION")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    debug: bool = Field(default=True, alias="DEBUG")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Server settings
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")

    # Nested settings
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    object_store: ObjectStoreSettings = Field(default_factory=ObjectStoreSettings)
    graph_store: GraphStoreSettings = Field(default_factory=GraphStoreSettings)
    vector_store: VectorStoreSettings = Field(default_factory=VectorStoreSettings)

    # API settings
    api_prefix: str = Field(default="/api/v1", alias="API_PREFIX")
    docs_url: Optional[str] = Field(default="/docs", alias="DOCS_URL")
    
    # Tracing
    enable_tracing: bool = Field(default=True, alias="ENABLE_TRACING")
    trace_sample_rate: float = Field(default=1.0, alias="TRACE_SAMPLE_RATE")


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.
    
    Settings are cached for performance. Use this function
    rather than instantiating Settings directly.
    """
    return Settings()


def get_database_settings() -> DatabaseSettings:
    """Get database settings."""
    return get_settings().database


def get_object_store_settings() -> ObjectStoreSettings:
    """Get object store settings."""
    return get_settings().object_store
