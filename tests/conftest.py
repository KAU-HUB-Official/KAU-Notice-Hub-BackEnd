import os

# 레이트리밋은 인메모리 카운터를 공유 app 싱글턴에 쌓으므로, 일반 테스트가
# 한도에 걸려 flaky 해지는 것을 막기 위해 테스트 스위트에서는 기본 비활성화한다.
# (한도 동작 자체는 tests/test_rate_limit.py가 격리된 app으로 검증한다.)
# get_settings()가 처음 호출되기 전에 설정해야 하므로 import 시점에 지정한다.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
