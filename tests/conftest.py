"""Integration tests require the Docker PostgreSQL service and a separate TEST database."""
import os
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.database import Base, get_db
from app.main import app

TEST_URL = os.getenv("TEST_DATABASE_URL")


@pytest_asyncio.fixture
async def client():
    if not TEST_URL:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")
    if "/shortener_test" not in TEST_URL:
        pytest.fail("TEST_DATABASE_URL must point to shortener_test database")
    engine = create_async_engine(TEST_URL)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def override_db():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000", follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()
