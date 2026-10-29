# tests/test_qa_regression.py
def test_qa_query_threshold():
    results = run_qa_tests(...)
    assert results.query_ok >= 27, \
        f"Query extraction regressed: {results.query_ok}/33"