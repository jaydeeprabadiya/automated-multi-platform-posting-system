import pytest

from app.platforms.base import BasePlatform


def test_base_platform_cannot_be_instantiated():
    with pytest.raises(TypeError):
        BasePlatform()


def test_concrete_platform_must_implement_publish():

    class IncompletePlatform(BasePlatform):

        @property
        def platform_name(self):
            return "Test"

    with pytest.raises(TypeError):
        IncompletePlatform()


def test_concrete_platform_must_implement_platform_name():

    class IncompletePlatform(BasePlatform):

        async def publish(self, message):
            return {"status": "success"}

    with pytest.raises(TypeError):
        IncompletePlatform()