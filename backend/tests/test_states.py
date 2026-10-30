import pytest

from botmanager.states import ALLOWED_TRANSITIONS, TERMINAL, InvalidTransition, RunStatus, check_transition


def test_terminal_states_have_no_exits():
    for s in TERMINAL:
        assert ALLOWED_TRANSITIONS[s] == frozenset()


@pytest.mark.parametrize("src,dst", [
    (RunStatus.PENDING, RunStatus.QUEUED),
    (RunStatus.PENDING, RunStatus.WAITING_APPROVAL),
    (RunStatus.WAITING_APPROVAL, RunStatus.QUEUED),
    (RunStatus.WAITING_APPROVAL, RunStatus.CANCELLED),
    (RunStatus.QUEUED, RunStatus.RUNNING),
    (RunStatus.RUNNING, RunStatus.SUCCEEDED),
    (RunStatus.RUNNING, RunStatus.FAILED),
    (RunStatus.RUNNING, RunStatus.CANCELLED),
])
def test_allowed(src, dst):
    check_transition(src, dst)


@pytest.mark.parametrize("src,dst", [
    (RunStatus.PENDING, RunStatus.RUNNING),
    (RunStatus.PENDING, RunStatus.SUCCEEDED),
    (RunStatus.WAITING_APPROVAL, RunStatus.RUNNING),
    (RunStatus.QUEUED, RunStatus.SUCCEEDED),
    (RunStatus.SUCCEEDED, RunStatus.FAILED),
    (RunStatus.FAILED, RunStatus.QUEUED),
    (RunStatus.CANCELLED, RunStatus.RUNNING),
])
def test_forbidden(src, dst):
    with pytest.raises(InvalidTransition):
        check_transition(src, dst)


def test_every_state_is_covered():
    assert set(ALLOWED_TRANSITIONS) == set(RunStatus)
