from agno.utils.functions import convert_function_result
from pydantic import BaseModel

def test_convert_function_result():
    assert convert_function_result("test") == "test"
    assert convert_function_result(1) == "1"
    assert convert_function_result(1.0) == "1.0"
    assert convert_function_result(True) == "true"
    assert convert_function_result(False) == "false"
    assert convert_function_result(None) == "None"
    assert convert_function_result({"success": True}) == '{"success": true}'
    assert convert_function_result({"apple", "banana"}) in ['["apple", "banana"]', '["banana", "apple"]']  # Order is not guaranteed in a set
    assert convert_function_result(("apple", "banana")) == '["apple", "banana"]'
    
    class MovieScript(BaseModel):
        title: str
        director: str
        year: int
        rating: float
    
    assert convert_function_result(MovieScript(title="The Dark Knight", director="Christopher Nolan", year=2008, rating=9.0)) == '{"title":"The Dark Knight","director":"Christopher Nolan","year":2008,"rating":9.0}'
