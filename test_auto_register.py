#!/usr/bin/env python
"""
Test script to demonstrate the auto-registration feature of the Toolkit class.
"""
import json
from libs.agno.agno.tools.calculator import CalculatorTools

def main():
    # Create a calculator with only add and subtract enabled
    calc = CalculatorTools(
        add=True, 
        subtract=True,
        multiply=False,
        divide=False
    )
    
    # Print registered functions
    print(f"Registered functions: {list(calc.functions.keys())}")
    
    # Test add function
    result = calc.add(5, 3)
    print(f"5 + 3 = {json.loads(result)['result']}")
    
    # Test subtract function
    result = calc.subtract(10, 4)
    print(f"10 - 4 = {json.loads(result)['result']}")
    
    # Create a calculator with all functions enabled
    calc_all = CalculatorTools(enable_all=True)
    print(f"All functions: {list(calc_all.functions.keys())}")
    
    # Test multiply function
    result = calc_all.multiply(6, 7)
    print(f"6 * 7 = {json.loads(result)['result']}")
    
    # Test a custom toolkit with auto-registration
    print("\nTesting custom toolkit with auto-registration:")
    from libs.agno.agno.tools import Toolkit
    
    class CustomToolkit(Toolkit):
        def __init__(self, **kwargs):
            super().__init__(name="custom_toolkit", auto_register=True, **kwargs)
            
        def hello(self, name: str) -> str:
            """Say hello to someone"""
            return f"Hello, {name}!"
            
        def goodbye(self, name: str) -> str:
            """Say goodbye to someone"""
            return f"Goodbye, {name}!"
    
    custom = CustomToolkit()
    print(f"Custom toolkit functions: {list(custom.functions.keys())}")
    print(custom.hello("World"))
    print(custom.goodbye("Python"))

if __name__ == "__main__":
    main() 