import os

import pytest

# 레이트리밋은 인메모리 카운터를 공유 app 싱글턴에 쌓으므로, 일반 테스트가
# 한도에 걸려 flaky 해지는 것을 막기 위해 테스트 스위트에서는 기본 비활성화한다.
# (한도 동작 자체는 tests/test_rate_limit.py가 격리된 app으로 검증한다.)
# get_settings()가 처음 호출되기 전에 설정해야 하므로 import 시점에 지정한다.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

# 이름 마스킹은 모델 파일(scripts/install_name_model.py)이 있어야 돈다. CI에는 모델이
# 없으므로 기본으로 끄고, 이름을 보는 테스트는 masking_on으로 가짜 모델을 끼우거나 실제 모델로 켠다.
os.environ.setdefault("PRIVACY_MASK_NAMES", "false")


@pytest.fixture
def masking_on(monkeypatch):
    """이름 마스킹을 켜고 가짜 모델(tests/fakes.FakeFinder)을 끼운다."""
    from app import name_masking
    from app.config import get_settings
    from app.name_masking import NameMasker

    def install(finder, cache=None):
        monkeypatch.setattr(get_settings(), "privacy_mask_names", True)
        monkeypatch.setattr(name_masking, "_masker", NameMasker(finder, cache))

    return install
