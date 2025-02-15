import json

from pydantic.alias_generators import to_snake

from phi.tools import Toolkit, Function

try:
    from apicaller import SwaggerCaller
except ImportError as e:
    raise ImportError("`apicaller` not installed. Please install using `pip install six urllib3 pyapicaller`")

def to_dict(obj):
    if isinstance(obj, list):
        return [to_dict(item) for item in obj]
    if hasattr(obj, 'to_dict'):
        return obj.to_dict()
    return obj

class ApiCaller(Toolkit):
    def __init__(
        self,
        swagger_client: str,
        openapi: str,
        path: str = 'swagger_clients',
        configuration: dict = None,
        generate_swagger = False
    ):
        super().__init__(name="apicaller")
        self._caller = SwaggerCaller(swagger_client, openapi, path=path, configuration=configuration)
        if generate_swagger:
            self._caller.generate()
        self.register_all()


    def register_all(self):
        def create_callable(function_name):
            def api_function(**kwargs):
                parameters = {to_snake(k): v for k, v in kwargs['parameters'].items()} if kwargs else {}
                response = self._caller.call_api(function_name, **parameters)
                return json.dumps(to_dict(response))
            return api_function

        for f_dict in self._caller.get_tools():
            f = Function(name=f_dict['function']['name'],
                         description=f_dict['function']['description'],
                         parameters=f_dict['function']['parameters'],
                         entrypoint=create_callable(f_dict['function']['name']))
            self.functions[f.name] = f
