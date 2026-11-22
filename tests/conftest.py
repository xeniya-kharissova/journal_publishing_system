"""Reusable pytest fixtures: isolated Alembic-migrated DB, TestClient, and auth helpers."""

from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.storage import LocalFilesystemStorageAdapter, StorageAdapter
from app.api.deps import get_storage_adapter
from app.core.config import Settings, get_settings
from app.core.database import Base, create_db_engine, create_session_factory, get_db
from app.main import create_app
from app.models.user import User

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def test_settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    """Create isolated test settings backed by a temporary SQLite database."""
    db_dir = tmp_path_factory.mktemp("test_db")
    db_path = db_dir / "test_journal.db"
    return Settings(
        environment="test",
        database_url=f"sqlite:///{db_path.as_posix()}",
        jwt_secret_key="test-suite-secret-key-at-least-32-characters-long",
        jwt_algorithm="HS256",
        access_token_expire_minutes=30,
        refresh_token_expire_days=7,
        cors_origins="http://localhost:3000,http://localhost:5173",
    )


@pytest.fixture(scope="session")
def migrated_engine(test_settings: Settings) -> Generator[Engine, None, None]:
    """Run real Alembic migrations against the isolated test database once per session."""
    alembic_cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", test_settings.database_url)
    command.upgrade(alembic_cfg, "head")

    engine = create_db_engine(test_settings.database_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def session_factory(migrated_engine: Engine) -> sessionmaker[Session]:
    """Return a SQLAlchemy session factory bound to the migrated test engine."""
    return create_session_factory(migrated_engine)


@pytest.fixture(autouse=True)
def clean_database(session_factory: sessionmaker[Session]) -> Generator[None, None, None]:
    """Clean all tables before and after every test to guarantee strict isolation."""
    def _clear_all_tables() -> None:
        with session_factory() as session:
            for table in reversed(Base.metadata.sorted_tables):
                session.execute(table.delete())
            session.commit()

    _clear_all_tables()
    yield
    _clear_all_tables()


@pytest.fixture
def db_session(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    """Provide a direct SQLAlchemy session for test setup or state inspection."""
    with session_factory() as session:
        yield session


@pytest.fixture
def storage_dir(tmp_path: Path) -> Path:
    """Provide an isolated per-test storage directory for uploaded manuscript files."""
    path = tmp_path / "storage"
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture
def storage_adapter(storage_dir: Path) -> StorageAdapter:
    """Provide a LocalFilesystemStorageAdapter rooted at the per-test temp directory."""
    return LocalFilesystemStorageAdapter(storage_dir)


@pytest.fixture
def client(
    test_settings: Settings,
    session_factory: sessionmaker[Session],
    storage_adapter: StorageAdapter,
) -> Generator[TestClient, None, None]:
    """Provide a FastAPI TestClient wired to the isolated test DB, settings, and storage."""
    app = create_app(test_settings)

    def _override_get_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_storage_adapter] = lambda: storage_adapter

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def register_user(client: TestClient) -> Callable[..., dict[str, Any]]:
    """Register a user via POST /api/v1/auth/register and return the response body."""
    def _register(
        *,
        email: str = "author@university.edu",
        password: str = "SecurePass123!",
        full_name: str = "Dr. Jane Author",
        affiliation: str | None = "Department of Computer Science",
    ) -> dict[str, Any]:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": password,
                "full_name": full_name,
                "affiliation": affiliation,
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    return _register


@pytest.fixture
def login_user(client: TestClient) -> Callable[..., dict[str, Any]]:
    """Log in via POST /api/v1/auth/login and return the token payload."""
    def _login(*, email: str, password: str = "SecurePass123!") -> dict[str, Any]:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        assert response.status_code == 200, response.text
        return response.json()

    return _login


@pytest.fixture
def auth_headers_for(login_user: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, str]]:
    """Return Bearer Authorization headers for a registered active user."""
    def _headers(*, email: str, password: str = "SecurePass123!") -> dict[str, str]:
        tokens = login_user(email=email, password=password)
        return {"Authorization": f"Bearer {tokens['access_token']}"}

    return _headers


@pytest.fixture
def admin_user(
    register_user: Callable[..., dict[str, Any]],
    db_session: Session,
) -> dict[str, Any]:
    """Create and return a System Administrator user."""
    created = register_user(
        email="admin@journal-platform.org",
        password="AdminPassword123!",
        full_name="Platform System Admin",
        affiliation="Journal Operations",
    )
    user = db_session.get(User, created["id"])
    assert user is not None
    user.is_system_admin = True
    db_session.commit()
    db_session.refresh(user)
    created["is_system_admin"] = True
    return created


@pytest.fixture
def admin_headers(
    admin_user: dict[str, Any],
    auth_headers_for: Callable[..., dict[str, str]],
) -> dict[str, str]:
    """Return Bearer Authorization headers for the System Administrator."""
    return auth_headers_for(
        email=admin_user["email"],
        password="AdminPassword123!",
    )
