import json
import os
from typing import List, Optional, Union

try:
    from agno.tools import Toolkit
    from agno.utils.log import log_debug, log_info, logger
except ImportError:
    raise ImportError("`agno` package not installed. Please install using `pip install agno`")

try:
    from langchain_apify import ApifyActorsTool
except ImportError:
    raise ImportError("`langchain_apify` not installed. Please install using `pip install langchain-apify`")

try:
    from apify_client import ApifyClient
except ImportError:
    raise ImportError("`apify_client` not installed. Please install using `pip install apify-client`")

class ApifyTools(Toolkit):
    def __init__(
        self,
        actors: Union[str, List[str]] = None,
        apify_api_token: Optional[str] = None
    ):
        """
        Initialize ApifyTools with specific Actors.

        Args:
            actors: Single Actor ID as string or list of Actor IDs to register as individual tools
            apify_api_token: Apify API token (defaults to APIFY_API_TOKEN env variable)
            register_generic: Whether to register the generic run_actor method
        """
        super().__init__(name="ApifyTools")
        
        # Get API token from args or environment
        self.apify_api_token = apify_api_token or os.getenv('APIFY_API_TOKEN')
        if not self.apify_api_token:
            raise ValueError("APIFY_API_TOKEN environment variable or apify_api_token parameter must be set")
        
        self.client = ApifyClient(self.apify_api_token)
        
        # Register specific Actors if provided
        if actors:
            actor_list = [actors] if isinstance(actors, str) else actors
            for actor_id in actor_list:
                self.register_actor(actor_id)
    
    def register_actor(self, actor_id: str) -> None:
        """
        Register an Apify Actor as a function in the toolkit.
        
        Args:
            actor_id: ID of the Apify Actor to register (e.g., 'apify/web-scraper')
        """
        try:
            actor_tool = ApifyActorsTool(actor_id=actor_id, apify_api_token=self.apify_api_token)
            tool_name = actor_tool.name

            # Create a wrapper function that calls the Actor tool
            def actor_function(**kwargs):
                try: 
                    # Params are nested under 'kwargs' key
                    if len(kwargs) == 1 and "kwargs" in kwargs:
                        kwargs = kwargs["kwargs"]
                        
                    # The actor tool expects run_input parameter
                    if len(kwargs) == 1 and "run_input" in kwargs:
                        run_input = kwargs["run_input"]
                    else:
                        run_input = kwargs

                    log_debug(f"Running Apify actor {actor_id} with parameters: {run_input}")
                    
                    # Run the Actor using langchain_apify's internal method
                    results = actor_tool.invoke({"run_input": run_input})
                    
                    string_representation = json.dumps(results)
                    return string_representation
                    
                except Exception as e:
                    error_msg = f"Error running Apify Actor {actor_id}: {str(e)}"
                    logger.error(error_msg)
                    return json.dumps([{"error": error_msg}])
            
            # Extract schema information for documentation
            schema_info = ""
            if hasattr(actor_tool, "args_schema") and hasattr(actor_tool.args_schema, "model_fields"):
                for field_name, field in actor_tool.args_schema.model_fields.items():
                    field_desc = field.description if hasattr(field, "description") and field.description else "No description available"
                    schema_info += f"\n    {field_name}: {field_desc}"
            
            # Update function metadata with improved docstring including schema
            actor_function.__name__ = tool_name
            actor_function.__doc__ = f"""
            {actor_tool.description}
            
            Input Schema:{schema_info}
            
            Fill in required, no need to fill in all inputs if it is not needed for any particular reason. 
                       
            Returns:
                String: JSON string containing the Actor's output dataset
            """
            
            # Register the function with the toolkit
            self.register(actor_function, sanitize_arguments=False)
            log_info(f"Registered Apify Actor '{actor_id}' as function '{tool_name}'")
            
        except Exception as e:
            logger.error(f"Failed to register Apify Actor '{actor_id}': {str(e)}")