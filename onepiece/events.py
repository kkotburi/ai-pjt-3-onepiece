"""단계 이벤트를 구독자에게 전달한다. 기록 실패는 메인 응답과 분리한다."""
import logging

_subscribers = []


def subscribe(listener):
    if listener not in _subscribers:
        _subscribers.append(listener)


def publish(session_id, kind, payload):
    for listener in _subscribers:
        try:
            listener(session_id, kind, payload)
        except Exception:
            logging.exception("실행 이벤트 저장 실패")
