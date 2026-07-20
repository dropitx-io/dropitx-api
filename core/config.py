from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Supabase (kept for Auth JWT verification only) ---
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""

    # --- Local PostgreSQL ---
    database_url: str = "postgresql://dropitx:dropitx_local_dev@localhost:5432/dropitx"

    # --- Local MinIO/S3 ---
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "dropitx"
    s3_secret_key: str = "dropitx_local_dev"

    # --- App ---
    allowed_origins: str = "http://localhost:3000"
    frontend_url: str = "http://localhost:3000"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def cors_origins(self) -> list[str]:
        if self.allowed_origins == "*":
            return ["*"]
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


settings = Settings()
