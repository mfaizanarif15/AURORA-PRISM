from types import SimpleNamespace

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes import update_current_user
from app.db.base import Base
from app.models import User
from app.schemas.api import AuthProfileUpdate
from app.services.auth import AuthUser, hash_password, verify_password


async def test_update_current_user_changes_profile_and_password() -> None:
    sessionmaker = await _sessionmaker()
    async with sessionmaker() as session:
        user = User(
            id="user-1",
            username="operator",
            display_name="Operator One",
            password_hash=hash_password("old-password"),
        )
        session.add(user)
        await session.commit()

        request = SimpleNamespace(
            headers={},
            query_params={},
            state=SimpleNamespace(
                auth_user=AuthUser(
                    id=user.id,
                    username=user.username,
                    display_name=user.display_name,
                )
            )
        )
        response = await update_current_user(
            AuthProfileUpdate(
                username="updated",
                display_name="Updated Operator",
                current_password="old-password",
                new_password="new-password",
            ),
            request,
            session,
        )

        await session.refresh(user)
        assert response.user.username == "updated"
        assert response.user.display_name == "Updated Operator"
        assert user.username == "updated"
        assert user.display_name == "Updated Operator"
        assert verify_password("new-password", user.password_hash)


async def _sessionmaker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)
