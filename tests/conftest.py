import pytest
from roth.example import internship_example
from roth.storage import empty_state


@pytest.fixture
def state():
    market, prefs = internship_example(students=5, internships=4)
    state = empty_state()
    state["market"] = market
    state["example_preferences"] = prefs
    return state
