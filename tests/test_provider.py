from app.llm.provider import get_llm


def test_llm_initialization():

    llm = get_llm()

    assert llm is not None