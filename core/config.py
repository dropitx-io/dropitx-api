from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Firebase Auth (ID token verification) ---
    firebase_project_id: str = ""

    # --- Local PostgreSQL ---
    database_url: str = "postgresql://dropitx:dropitx_local_dev@localhost:5432/dropitx"

    # --- Local MinIO/S3 ---
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "dropitx"
    s3_secret_key: str = "dropitx_local_dev"
    # Browser-facing base URL of the object store, used to build URLs of public assets.
    storage_public_url: str = "http://localhost:9000"

    # --- App ---
    allowed_origins: str = "http://localhost:3000"
    frontend_url: str = "http://localhost:3000"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def cors_origins(self) -> list[str]:
        if self.allowed_origins == "*":
            return ["*"]
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


settings = Settings()
