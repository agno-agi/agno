from agno.app.fastapi.app import FastAPIApp
from agno.workflow import Workflow


class TargetInfoRetriever(Workflow):
    # Some agent initialization-related code

    def run(self, query: str):
        return "test"


workflow = TargetInfoRetriever()
workflow.workflow_id = "target_info_retriever"

fastapi_app = FastAPIApp(
    workflows=[workflow],
    name="Target Info Retriever",
    app_id="target_info_retriever",
    description="A target info retriever agent that can retriever the relevant data about your input.",
)

app = fastapi_app.get_app()

if __name__ == "__main__":
    fastapi_app.serve(app="support:app", port=8001, reload=True)
