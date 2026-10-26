# 04_workflows/05_conditional_branching

## Scope
Runnable workflow examples under: cookbook/04_workflows/05_conditional_branching

## Files
- loop_in_choices.py: Demonstrates loop in choices.
- nested_choices.py: Demonstrates nested choices.
- router_basic.py: Demonstrates router basic.
- [router_jev_classifier.py](router_jev_classifier.py): Jev classifies a support request; a Router forwards the original message to a specialist. Requires `typesafe-sdk`, `TYPESAFE_API_KEY`, and `OPENAI_API_KEY`; see [Jev setup](../../90_models/typesafe/README.md).
- router_with_loop.py: Demonstrates router with loop.
- selector_media_pipeline.py: Demonstrates selector media pipeline.
- selector_types.py: Demonstrates selector types.
- step_choices_parameter.py: Demonstrates step choices parameter.
- string_selector.py: Demonstrates string selector.

## Prerequisites
- Activate the demo environment: .venvs/demo/bin/python
- Load API keys with direnv allow (requires a local .envrc file).
